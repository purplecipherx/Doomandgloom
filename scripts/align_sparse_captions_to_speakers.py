#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import sqlite3
from collections import defaultdict
from pathlib import Path

def clean(x): return str(x or "").strip()

def load_resolution(path:Path,channel_id:str,moji_output:Path):
    out={}; target=str(moji_output.resolve()).lower()
    if not path.exists(): return out
    for r in csv.DictReader(path.open(encoding="utf-8-sig")):
        if channel_id and clean(r.get("channel_id")) and clean(r.get("channel_id"))!=channel_id: continue
        pid=clean(r.get("pipeline_cluster_id"))
        if not pid: continue
        score=0
        if clean(r.get("moji_output_path")).lower()==target: score+=100
        st=clean(r.get("binding_status") or r.get("identity_status")).upper()
        if st=="VERIFIED": score+=20
        elif st=="HIGH_CONFIDENCE": score+=10
        try: score+=float(r.get("confidence") or 0)
        except Exception: pass
        if pid not in out or score>out[pid][0]: out[pid]=(score,r)
    return {k:v[1] for k,v in out.items()}

def main():
    ap=argparse.ArgumentParser(description="Propagate sparse voice samples onto caption cues conservatively.")
    ap.add_argument("--moji-output",required=True)
    ap.add_argument("--sample-manifest",required=True)
    ap.add_argument("--normalized-dir",required=True)
    ap.add_argument("--speaker-resolution",default="")
    ap.add_argument("--channel-id",default="")
    ap.add_argument("--output",required=True)
    ap.add_argument("--medium-max-distance",type=float,default=60.0)
    ap.add_argument("--bracket-max-distance",type=float,default=150.0)
    args=ap.parse_args()

    moji=Path(args.moji_output).resolve()
    manifest=Path(args.sample_manifest).resolve()
    normalized=Path(args.normalized_dir).resolve()
    out=Path(args.output).resolve(); out.mkdir(parents=True,exist_ok=True)
    db=moji/"voice_harvester.sqlite"
    if not db.exists(): raise SystemExit(f"Missing {db}")

    sample_rows=[]
    for line in manifest.read_text(encoding="utf-8",errors="replace").splitlines():
        if not line.strip(): continue
        try: sample_rows.append(json.loads(line))
        except Exception: pass
    by_clip={str(Path(r["clip_path"]).resolve()):r for r in sample_rows if r.get("clip_path")}

    c=sqlite3.connect(db); c.row_factory=sqlite3.Row
    rows=c.execute(
        """SELECT sf.path,ls.local_speaker,sa.global_speaker_id
           FROM source_files sf
           JOIN local_speakers ls ON ls.file_id=sf.id
           LEFT JOIN speaker_assignments sa ON sa.local_speaker_id=ls.id"""
    ).fetchall()
    c.close()

    resolution=load_resolution(Path(args.speaker_resolution).resolve(),args.channel_id,moji) if args.speaker_resolution else {}

    samples_by_video=defaultdict(list)
    for r in rows:
        meta=by_clip.get(str(Path(r["path"]).resolve()))
        if not meta: continue
        gid=clean(r["global_speaker_id"]) or clean(r["local_speaker"])
        rr=resolution.get(gid,{})
        voice_key=clean(rr.get("canonical_voice_id")) or gid
        samples_by_video[clean(meta.get("video_id"))].append({
            "gid":gid,"voice_key":voice_key,
            "cue_index":int(meta.get("cue_index") or 0),
            "start":float(meta.get("start_seconds") or 0),
            "end":float(meta.get("end_seconds") or 0),
            "center":(float(meta.get("start_seconds") or 0)+float(meta.get("end_seconds") or 0))/2.0,
            "sample_id":clean(meta.get("sample_id")),
            "audio_sha256":clean(meta.get("source_audio_sha256")),
            "url":clean(meta.get("source_url")),
            "title":clean(meta.get("title")),
        })
    for v in samples_by_video.values(): v.sort(key=lambda x:x["center"])

    output=[]
    for cap in sorted(normalized.glob("*.segments.jsonl")):
        vid=cap.name[:-len(".segments.jsonl")]
        samples=samples_by_video.get(vid,[])
        for cue_index,line in enumerate(cap.read_text(encoding="utf-8",errors="replace").splitlines()):
            if not line.strip(): continue
            try:q=json.loads(line)
            except Exception: continue
            qs=float(q.get("start") or 0); qe=float(q.get("end") or qs); center=(qs+qe)/2.0
            before=max((s for s in samples if s["center"]<=center),key=lambda x:x["center"],default=None)
            after=min((s for s in samples if s["center"]>=center),key=lambda x:x["center"],default=None)
            nearest=min(samples,key=lambda s:abs(s["center"]-center),default=None)
            gid=""; status="NO_SPEECH_MATCH"; distance=""; method="sparse_no_sample"; candidates=[]
            if nearest:
                nd=abs(nearest["center"]-center); distance=round(nd,3)
                candidates=[nearest]
                if int(nearest["cue_index"])==cue_index:
                    gid=nearest["gid"]; status="ATTRIBUTED_HIGH"; method="sparse_exact_sample"
                elif before and after and before["voice_key"]==after["voice_key"] and                      abs(center-before["center"])<=args.bracket_max_distance and                      abs(after["center"]-center)<=args.bracket_max_distance:
                    gid=before["gid"]; status="ATTRIBUTED_HIGH"; method="sparse_same_voice_bracket"; candidates=[before,after]
                elif before and after and before["voice_key"]!=after["voice_key"] and before["sample_id"]!=after["sample_id"]:
                    status="AMBIGUOUS"; method="sparse_conflicting_bracket"; candidates=[before,after]
                elif nd<=args.medium_max_distance:
                    gid=nearest["gid"]; status="ATTRIBUTED_MEDIUM"; method="sparse_nearest"
                else:
                    status="AMBIGUOUS"; method="sparse_sample_too_distant"
            rr=resolution.get(gid,{}) if gid else {}
            meta=nearest or {}
            output.append({
                "channel_id":args.channel_id,"video_id":vid,"canonical_url":clean(meta.get("url")),
                "title":clean(meta.get("title")),"cue_index":cue_index,"start_seconds":qs,"end_seconds":qe,
                "text":clean(q.get("text")),"raw_speaker_id":gid,
                "acoustic_cluster_id":clean(rr.get("cluster_observation_id")),
                "canonical_voice_id":clean(rr.get("canonical_voice_id")),
                "resolved_entity_id":clean(rr.get("resolved_entity_id")),
                "speaker_display_name":clean(rr.get("display_name")),
                "speaker_resolution_status":clean(rr.get("binding_status") or rr.get("identity_status")),
                "speaker_resolution_confidence":clean(rr.get("confidence")),
                "speaker_attribution_status":status,
                "speaker_coverage_ratio":"","dominant_speaker_share":"","second_speaker_share":"",
                "speaker_count":1 if gid else 0,"overlap_speech_seconds":"",
                "candidate_speakers_json":json.dumps([
                    {"speaker_id":x["gid"],"sample_id":x["sample_id"],"distance_seconds":round(abs(x["center"]-center),3)}
                    for x in candidates
                ],ensure_ascii=False),
                "caption_source_path":str(cap),"audio_sha256":clean(meta.get("audio_sha256")),
                "attribution_method":method,"nearest_sample_distance_seconds":distance,
            })

    fields=[
        "channel_id","video_id","canonical_url","title","cue_index","start_seconds","end_seconds","text",
        "raw_speaker_id","acoustic_cluster_id","canonical_voice_id","resolved_entity_id","speaker_display_name",
        "speaker_resolution_status","speaker_resolution_confidence","speaker_attribution_status",
        "speaker_coverage_ratio","dominant_speaker_share","second_speaker_share","speaker_count",
        "overlap_speech_seconds","candidate_speakers_json","caption_source_path","audio_sha256",
        "attribution_method","nearest_sample_distance_seconds"
    ]
    with (out/"caption_speaker_attribution.csv").open("w",newline="",encoding="utf-8-sig") as f:
        w=csv.DictWriter(f,fieldnames=fields); w.writeheader(); w.writerows(output)
    with (out/"caption_speaker_attribution.jsonl").open("w",encoding="utf-8") as f:
        for r in output:f.write(json.dumps(r,ensure_ascii=False)+"\n")
    counts=defaultdict(int)
    for r in output: counts[r["speaker_attribution_status"]]+=1
    summary={"channel_id":args.channel_id,"row_count":len(output),"status_counts":dict(counts),
             "sample_count":len(sample_rows),"method":"sparse_caption_guided_voice_sampling"}
    (out/"caption_speaker_attribution_manifest.json").write_text(json.dumps(summary,indent=2),encoding="utf-8")
    print(json.dumps(summary,indent=2))
    return 0

if __name__=="__main__":
    raise SystemExit(main())
