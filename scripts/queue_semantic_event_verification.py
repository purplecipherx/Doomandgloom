#!/usr/bin/env python3
from __future__ import annotations

import argparse,csv,hashlib,json
from datetime import datetime,timezone
from pathlib import Path

from pipeline_client import enqueue

def now():
    return datetime.now(timezone.utc).isoformat()

def read_csv(path):
    p=Path(path)
    if not p.exists(): return []
    return list(csv.DictReader(p.open(encoding="utf-8-sig")))

def bid(ids):
    return "SV_"+hashlib.sha256("|".join(ids).encode("utf-8")).hexdigest()[:20].upper()

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--analysis-dir",default="data/analysis")
    ap.add_argument("--output-dir",default="data/analysis/semantic_verification_batches")
    ap.add_argument("--batch-size",type=int,default=40)
    ap.add_argument("--hub",default="")
    args=ap.parse_args()

    ad=Path(args.analysis_dir).resolve()
    out=Path(args.output_dir).resolve(); pending_dir=out/"pending"; pending_dir.mkdir(parents=True,exist_ok=True)

    units=read_csv(ad/"transcript_units.csv")
    current=[u for u in units if u.get("source_status","CURRENT")=="CURRENT"]
    unit_map={u["unit_id"]:u for u in current}
    by_content={}
    for u in current: by_content.setdefault(u.get("content_id",""),[]).append(u)
    for rows in by_content.values():
        rows.sort(key=lambda r:float(r.get("start_seconds") or 0))
    context={}
    for rows in by_content.values():
        for i,u in enumerate(rows):
            context[u["unit_id"]]={
                "before":[{"unit_id":x["unit_id"],"speaker_id":x.get("speaker_id",""),"text":x.get("text","")} for x in rows[max(0,i-2):i]],
                "after":[{"unit_id":x["unit_id"],"speaker_id":x.get("speaker_id",""),"text":x.get("text","")} for x in rows[i+1:i+3]]
            }

    events=read_csv(ad/"semantic_events.csv")
    existing={r.get("semantic_event_id",""):r for r in read_csv(ad/"semantic_event_verifications.csv")}
    pending=[
        e for e in events
        if e.get("unit_id","") in unit_map
        and existing.get(e.get("semantic_event_id",""),{}).get("status") not in {"VERIFIED_TEXT","REJECTED_TEXT"}
    ]

    index_path=out/"verification_batch_index.csv"
    old_index={r.get("semantic_event_id",""):r for r in read_csv(index_path)}
    pending=[e for e in pending if old_index.get(e.get("semantic_event_id",""),{}).get("status") not in {"PENDING","QUEUED"}]

    created=[]; new_index=[]
    size=max(1,args.batch_size)
    for i in range(0,len(pending),size):
        chunk=pending[i:i+size]
        ids=[e["semantic_event_id"] for e in chunk]
        batch=bid(ids); path=pending_dir/f"{batch}.jsonl"
        with path.open("w",encoding="utf-8") as f:
            for e in chunk:
                u=unit_map[e["unit_id"]]
                rec={
                    "batch_id":batch,
                    "semantic_event":e,
                    "source_unit":{
                        "unit_id":u["unit_id"],"content_id":u.get("content_id",""),
                        "speaker_id":u.get("speaker_id",""),"canonical_voice_id":u.get("canonical_voice_id",""),
                        "resolved_entity_id":u.get("resolved_entity_id",""),
                        "start_seconds":u.get("start_seconds",""),"end_seconds":u.get("end_seconds",""),
                        "text":u.get("text",""),"source_path":u.get("source_path","")
                    },
                    "context_before":context.get(u["unit_id"],{}).get("before",[]),
                    "context_after":context.get(u["unit_id"],{}).get("after",[]),
                    "verify":{
                        "question":"Does the transcript/context actually support this semantic event exactly as encoded?",
                        "allowed_statuses":["VERIFIED_TEXT","NEEDS_REVIEW","REJECTED_TEXT"],
                        "check_error_types":[
                            "WRONG_SPEAKER","WRONG_TARGET","WRONG_PREDICATE","OVERSTATED","UNDERSTATED",
                            "QUOTE_TO_BELIEF","HEARSAY_TO_BELIEF","ALLEGATION_TO_FACT","NEGATION_INVERSION",
                            "QUESTION_TO_ASSERTION","HYPOTHETICAL_TO_ASSERTION","PREDICTION_TO_OBSERVED_EVENT",
                            "MENTION_TO_RELATIONSHIP","CRITICISM_TO_ASSOCIATION","RECOMMENDATION_TO_AFFILIATE",
                            "SHARED_TARGET_TO_COORDINATION","COREFERENCE_GUESSED","ENTITY_RESOLUTION_ERROR",
                            "TRANSCRIPT_FRAGMENT_ERROR","MISSING_CONTEXT","DUPLICATE_EVENT"
                        ],
                        "truth_check_is_out_of_scope":True
                    }
                }
                f.write(json.dumps(rec,ensure_ascii=False)+"\n")
        for eid in ids:
            row={"semantic_event_id":eid,"batch_id":batch,"batch_path":str(path),"created_at":now(),"status":"PENDING"}
            old_index[eid]=row;new_index.append(row)
        if args.hub:
            enqueue(args.hub,kind="semantic_event_verification_batch",lane="review",
                    payload={"batch_id":batch,"batch_path":str(path),"event_count":len(chunk)},
                    job_key=f"semantic_verify:{batch}",priority=90,max_attempts=1)
        created.append({"batch_id":batch,"batch_path":str(path),"event_count":len(chunk)})

    fields=["semantic_event_id","batch_id","batch_path","created_at","status"]
    with index_path.open("w",newline="",encoding="utf-8-sig") as f:
        w=csv.DictWriter(f,fieldnames=fields);w.writeheader()
        for r in sorted(old_index.values(),key=lambda r:(r.get("batch_id",""),r.get("semantic_event_id",""))):w.writerow(r)

    manifest={"created_at":now(),"pending_events_seen":len(pending),"new_batches":created,"new_index_rows":len(new_index)}
    (out/"verification_queue_manifest.json").write_text(json.dumps(manifest,indent=2),encoding="utf-8")
    print(json.dumps(manifest,indent=2))
    return 0

if __name__=="__main__":
    raise SystemExit(main())
