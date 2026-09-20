#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from pipeline_client import enqueue

def now():
    return datetime.now(timezone.utc).isoformat()

def batch_id(unit_ids):
    raw="|".join(unit_ids).encode("utf-8")
    return "SR_" + hashlib.sha256(raw).hexdigest()[:20].upper()

def load_index(path: Path):
    if not path.exists():
        return {}
    return {r["unit_id"]: r for r in csv.DictReader(path.open(encoding="utf-8-sig"))}

def load_caption_attributions(root: Path):
    exact = {}
    by_video = {}
    if not root.exists():
        return {"exact": exact, "by_video": by_video}
    for p in root.rglob("caption_speaker_attribution.csv"):
        try:
            rows = list(csv.DictReader(p.open(encoding="utf-8-sig")))
            for r in rows:
                vid = r.get("video_id", "")
                try:
                    st = float(r.get("start_seconds") or 0)
                    en = float(r.get("end_seconds") or st)
                except Exception:
                    continue
                text_key = " ".join((r.get("text") or "").split()).lower()
                exact[(vid, round(st,3), round(en,3), text_key)] = r
                rr=dict(r); rr["_start"]=st; rr["_end"]=en
                by_video.setdefault(vid,[]).append(rr)
        except Exception:
            continue
    for rows in by_video.values():
        rows.sort(key=lambda r:(r["_start"],r["_end"]))
    return {"exact": exact, "by_video": by_video}

def _interval_union_length(intervals):
    if not intervals:
        return 0.0
    xs=sorted((max(0.0,a),max(0.0,b)) for a,b in intervals if b>a)
    if not xs:
        return 0.0
    total=0.0; cur_a,cur_b=xs[0]
    for a,b in xs[1:]:
        if a<=cur_b:
            cur_b=max(cur_b,b)
        else:
            total+=cur_b-cur_a; cur_a,cur_b=a,b
    total+=cur_b-cur_a
    return total

def attribution_for(row, attribution):
    try:
        vid=row.get("content_id","")
        st=float(row.get("start_seconds") or 0)
        en=float(row.get("end_seconds") or st)
        text_key=" ".join((row.get("text") or "").split()).lower()
    except Exception:
        return {}

    exact=attribution.get("exact",{})
    key=(vid,round(st,3),round(en,3),text_key)
    if key in exact:
        return exact[key]

    candidates=attribution.get("by_video",{}).get(vid,[])
    if not candidates:
        return {}
    duration=max(0.001,en-st)
    scores={}
    rep={}
    coverage_intervals=[]
    status_weight={"ATTRIBUTED_HIGH":1.0,"ATTRIBUTED_MEDIUM":0.8,"AMBIGUOUS":0.45,"NO_SPEECH_MATCH":0.0}

    for a in candidates:
        ast=float(a.get("_start") or 0); aen=float(a.get("_end") or ast)
        ov=max(0.0,min(en,aen)-max(st,ast))
        if ov<=0:
            continue
        coverage_intervals.append((max(st,ast)-st,min(en,aen)-st))
        q=status_weight.get(a.get("speaker_attribution_status",""),0.6)
        try:
            raw_candidates=json.loads(a.get("candidate_speakers_json") or "[]")
        except Exception:
            raw_candidates=[]
        if raw_candidates:
            for c in raw_candidates:
                spk=c.get("speaker_id","")
                if not spk: continue
                try: share=float(c.get("share") or 0)
                except Exception: share=0.0
                scores[spk]=scores.get(spk,0.0)+ov*max(0.0,share)*q
                old=rep.get(spk)
                if old is None or ov*q > old[0]:
                    rep[spk]=(ov*q,a)
        else:
            spk=a.get("raw_speaker_id","")
            if spk:
                scores[spk]=scores.get(spk,0.0)+ov*q
                old=rep.get(spk)
                if old is None or ov*q > old[0]:
                    rep[spk]=(ov*q,a)

    if not scores:
        return {}
    ranked=sorted(scores.items(),key=lambda x:(-x[1],x[0]))
    top_id,top_score=ranked[0]
    total=sum(scores.values())
    dominant=top_score/total if total>0 else 0.0
    second=ranked[1][1]/total if len(ranked)>1 and total>0 else 0.0
    coverage=min(1.0,_interval_union_length(coverage_intervals)/duration)
    representative=(rep.get(top_id) or (0,{}))[1]

    if coverage<0.35:
        status="NO_SPEECH_MATCH"
    elif dominant>=0.80 and second<=0.20:
        status="ATTRIBUTED_HIGH"
    elif dominant>=0.65 and second<=0.35:
        status="ATTRIBUTED_MEDIUM"
    else:
        status="AMBIGUOUS"

    out=dict(representative)
    out.update({
        "video_id":vid,
        "start_seconds":st,
        "end_seconds":en,
        "text":row.get("text",""),
        "raw_speaker_id":top_id,
        "speaker_attribution_status":status,
        "speaker_coverage_ratio":round(coverage,6),
        "dominant_speaker_share":round(dominant,6),
        "second_speaker_share":round(second,6),
        "speaker_count":len(ranked),
        "candidate_speakers_json":json.dumps([
            {"speaker_id":spk,"share":round(score/total,6) if total else 0.0}
            for spk,score in ranked
        ],ensure_ascii=False),
    })
    return out

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--ledger",default="data/analysis/transcript_units.csv")
    ap.add_argument("--output-dir",default="data/analysis/review_batches")
    ap.add_argument("--batch-size",type=int,default=40)
    ap.add_argument("--hub",default="")
    ap.add_argument("--speaker-attribution-root",default="")
    args=ap.parse_args()

    ledger=Path(args.ledger).resolve()
    out=Path(args.output_dir).resolve()
    repo_root=ledger.parents[2] if len(ledger.parents)>=3 else Path.cwd()
    attribution_root=Path(args.speaker_attribution_root).resolve() if args.speaker_attribution_root else repo_root/"research"/"youtube"
    caption_attribution=load_caption_attributions(attribution_root)
    pending_dir=out/"pending"; pending_dir.mkdir(parents=True,exist_ok=True)
    index_path=out/"review_batch_index.csv"
    index=load_index(index_path)

    rows=list(csv.DictReader(ledger.open(encoding="utf-8-sig")))
    current_rows=[r for r in rows if r.get("source_status","CURRENT")=="CURRENT"]
    current_ids={r["unit_id"] for r in current_rows}
    for uid,entry in index.items():
        if uid not in current_ids and entry.get("status") in {"PENDING","QUEUED",""}:
            entry["status"]="SUPERSEDED"
    by_content={}
    for r in current_rows:
        by_content.setdefault(r["content_id"],[]).append(r)
    for content_rows in by_content.values():
        def _t(x):
            try: return float(x.get("start_seconds") or 0)
            except Exception: return 0.0
        content_rows.sort(key=lambda x: (_t(x), x.get("unit_id","")))
    neighbor_map={}
    for content_rows in by_content.values():
        for idx,r in enumerate(content_rows):
            def ctx(x):
                a=attribution_for(x,caption_attribution)
                return {
                    "unit_id":x.get("unit_id",""),
                    "speaker_id":a.get("raw_speaker_id") or x.get("speaker_id",""),
                    "raw_speaker_id":a.get("raw_speaker_id") or x.get("raw_speaker_id",""),
                    "acoustic_cluster_id":a.get("acoustic_cluster_id") or x.get("acoustic_cluster_id",""),
                    "canonical_voice_id":a.get("canonical_voice_id") or x.get("canonical_voice_id",""),
                    "resolved_entity_id":a.get("resolved_entity_id") or x.get("resolved_entity_id",""),
                    "speaker_display_name":a.get("speaker_display_name") or x.get("speaker_display_name",""),
                    "speaker_attribution_status":a.get("speaker_attribution_status",""),
                    "dominant_speaker_share":a.get("dominant_speaker_share",""),
                    "speaker_coverage_ratio":a.get("speaker_coverage_ratio",""),
                    "candidate_speakers_json":a.get("candidate_speakers_json",""),
                    "text":x.get("text",""),
                }
            neighbor_map[r["unit_id"]]={
                "context_before":[ctx(x) for x in content_rows[max(0,idx-2):idx]],
                "context_after":[ctx(x) for x in content_rows[idx+1:idx+3]],
            }

    deferred_unattributed = [
        r for r in current_rows
        if r.get("source_type")=="youtube_caption"
        and not attribution_for(r,caption_attribution)
        and r.get("semantic_review_status")!="COMPLETE"
        and r["unit_id"] not in index
    ]
    pending=[
        r for r in current_rows
        if r.get("semantic_review_status")!="COMPLETE"
        and r["unit_id"] not in index
        and (r.get("source_type")!="youtube_caption" or attribution_for(r,caption_attribution))
    ]

    new_index=[]
    created=[]
    size=max(1,args.batch_size)
    for i in range(0,len(pending),size):
        chunk=pending[i:i+size]
        ids=[r["unit_id"] for r in chunk]
        bid=batch_id(ids)
        path=pending_dir/f"{bid}.jsonl"
        with path.open("w",encoding="utf-8") as f:
            for r in chunk:
                a=attribution_for(r,caption_attribution)
                rec={
                    "batch_id":bid,
                    "unit_id":r["unit_id"],
                    "content_id":r["content_id"],
                    "source_type":r["source_type"],
                    "source_path":r["source_path"],
                    "start_seconds":r["start_seconds"],
                    "end_seconds":r["end_seconds"],
                    "speaker_id":a.get("raw_speaker_id") or r["speaker_id"],
                    "raw_speaker_id":a.get("raw_speaker_id") or r.get("raw_speaker_id",""),
                    "acoustic_cluster_id":a.get("acoustic_cluster_id") or r.get("acoustic_cluster_id",""),
                    "canonical_voice_id":a.get("canonical_voice_id") or r.get("canonical_voice_id",""),
                    "resolved_entity_id":a.get("resolved_entity_id") or r.get("resolved_entity_id",""),
                    "speaker_resolution_status":a.get("speaker_resolution_status") or r.get("speaker_resolution_status",""),
                    "speaker_resolution_confidence":a.get("speaker_resolution_confidence") or r.get("speaker_resolution_confidence",""),
                    "speaker_display_name":a.get("speaker_display_name") or r.get("speaker_display_name",""),
                    "speaker_attribution_status":a.get("speaker_attribution_status",""),
                    "speaker_coverage_ratio":a.get("speaker_coverage_ratio",""),
                    "dominant_speaker_share":a.get("dominant_speaker_share",""),
                    "second_speaker_share":a.get("second_speaker_share",""),
                    "candidate_speakers_json":a.get("candidate_speakers_json",""),
                    "channel_id":a.get("channel_id") or r.get("channel_id",""),
                    "text":r["text"],
                    "context_before":neighbor_map.get(r["unit_id"],{}).get("context_before",[]),
                    "context_after":neighbor_map.get(r["unit_id"],{}).get("context_after",[]),
                    "review_required":{
                        "ontology_path":"data/ontology/investigative_predicates.csv",
                        "event_schema_path":"data/ontology/semantic_event_schema.json",
                        "extract_semantic_events":True,
                        "preserve_raw_predicate_phrase":True,
                        "classify_speech_act":True,
                        "extract_all_mentions":True,
                        "resolve_fragmented_or_mistranscribed_names":True,
                        "extract_atomic_claims":True,
                        "extract_claims_about_people_or_orgs":True,
                        "extract_stances":True,
                        "extract_rhetorical_devices_and_scare_tactics":True,
                        "extract_speaker_identity_clues":True,
                        "extract_relationship_assertions_without_promoting_to_fact":True,
                        "extract_products_services_sponsors_ctas":True,
                        "extract_predictions":True,
                        "extract_money_conflict_signals":True,
                        "extract_citations_sources_mentioned":True,
                        "fact_check_every_atomic_factual_claim":True,
                        "critical_errors_to_avoid":[
                            "mention_to_relationship",
                            "criticism_to_association",
                            "quotation_to_speaker_belief",
                            "allegation_to_fact",
                            "negation_inversion",
                            "wrong_claimant",
                            "wrong_target",
                            "recommendation_to_affiliate_relationship",
                            "prediction_to_observed_event",
                            "shared_target_to_coordination"
                        ]
                    }
                }
                f.write(json.dumps(rec,ensure_ascii=False)+"\n")
        for r in chunk:
            entry={"unit_id":r["unit_id"],"batch_id":bid,"batch_path":str(path),"created_at":now(),"status":"PENDING"}
            index[r["unit_id"]]=entry; new_index.append(entry)
        if args.hub:
            enqueue(args.hub,kind="semantic_review_batch",lane="review",
                    payload={"batch_id":bid,"batch_path":str(path),"unit_count":len(chunk)},
                    job_key=f"review:{bid}",priority=100,max_attempts=1)
        created.append({"batch_id":bid,"path":str(path),"unit_count":len(chunk)})

    fields=["unit_id","batch_id","batch_path","created_at","status"]
    with index_path.open("w",newline="",encoding="utf-8-sig") as f:
        w=csv.DictWriter(f,fieldnames=fields); w.writeheader()
        for r in sorted(index.values(),key=lambda x:(x["batch_id"],x["unit_id"])): w.writerow(r)

    manifest={"created_at":now(),"ledger":str(ledger),"new_batches":created,"new_units":len(new_index),
              "total_indexed_units":len(index),"deferred_unattributed_caption_units":len(deferred_unattributed),
              "hub":args.hub or None}
    (out/"review_queue_manifest.json").write_text(json.dumps(manifest,indent=2),encoding="utf-8")
    print(json.dumps(manifest,indent=2))
    return 0

if __name__=="__main__":
    raise SystemExit(main())
