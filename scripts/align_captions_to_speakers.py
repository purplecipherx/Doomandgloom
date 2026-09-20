#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import sqlite3
from collections import defaultdict
from pathlib import Path


def clean(x):
    return str(x or "").strip()


def resolve_audio_path(manifest: Path, rel: str):
    p=Path(rel)
    if p.is_absolute():
        return p.resolve()
    candidates=[(manifest.parent/p).resolve(),(manifest.parent.parent/p).resolve()]
    return next((x for x in candidates if x.exists()),candidates[0])


def load_audio_manifest(path:Path):
    by_path={}
    by_video={}
    if not path.exists():
        return by_path,by_video
    for line in path.read_text(encoding="utf-8",errors="replace").splitlines():
        if not line.strip():
            continue
        try:r=json.loads(line)
        except Exception:continue
        vid=clean(r.get("video_id"))
        ap=clean(r.get("audio_path"))
        if vid:
            by_video[vid]=r
        if ap:
            by_path[str(resolve_audio_path(path,ap))]=r
    return by_path,by_video


def load_resolution(path:Path,channel_id:str,moji_output:Path):
    out={}
    if not path.exists():
        return out
    target=str(moji_output.resolve()).lower()
    candidates=defaultdict(list)
    for r in csv.DictReader(path.open(encoding="utf-8-sig")):
        if channel_id and clean(r.get("channel_id")) and clean(r.get("channel_id"))!=channel_id:
            continue
        pid=clean(r.get("pipeline_cluster_id"))
        if not pid:
            continue
        score=0
        mop=clean(r.get("moji_output_path")).lower()
        if mop and mop==target:
            score+=100
        status=clean(r.get("binding_status") or r.get("identity_status")).upper()
        if status=="VERIFIED":score+=20
        elif status=="HIGH_CONFIDENCE":score+=10
        try:score+=float(r.get("confidence") or 0)
        except Exception:pass
        candidates[pid].append((score,r))
    for pid,rows in candidates.items():
        out[pid]=max(rows,key=lambda x:x[0])[1]
    return out


def overlap(a0,a1,b0,b1):
    return max(0.0,min(a1,b1)-max(a0,b0))


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--moji-output",required=True)
    ap.add_argument("--normalized-dir",required=True)
    ap.add_argument("--audio-manifest",required=True)
    ap.add_argument("--speaker-resolution",default="")
    ap.add_argument("--channel-id",default="")
    ap.add_argument("--output",required=True)
    ap.add_argument("--high-dominant-share",type=float,default=0.80)
    ap.add_argument("--medium-dominant-share",type=float,default=0.65)
    ap.add_argument("--min-coverage",type=float,default=0.35)
    args=ap.parse_args()

    moji=Path(args.moji_output).resolve()
    normalized=Path(args.normalized_dir).resolve()
    manifest=Path(args.audio_manifest).resolve()
    out=Path(args.output).resolve()
    out.mkdir(parents=True,exist_ok=True)

    db=moji/"voice_harvester.sqlite"
    if not db.exists():
        raise SystemExit(f"Missing Moji DB: {db}")
    by_path,by_video=load_audio_manifest(manifest)
    resolution=load_resolution(Path(args.speaker_resolution).resolve(),args.channel_id,moji) if args.speaker_resolution else {}

    conn=sqlite3.connect(db); conn.row_factory=sqlite3.Row
    rows=conn.execute(
        """SELECT sf.id AS file_id,sf.path,s.local_speaker,s.start,s.end,s.duration,s.overlap,
                  sa.global_speaker_id
           FROM segments s
           JOIN source_files sf ON sf.id=s.file_id
           JOIN local_speakers ls ON ls.file_id=s.file_id AND ls.local_speaker=s.local_speaker
           LEFT JOIN speaker_assignments sa ON sa.local_speaker_id=ls.id
           ORDER BY sf.id,s.start,s.end"""
    ).fetchall()
    conn.close()

    seg_by_video=defaultdict(list)
    for r in rows:
        source=str(Path(r["path"]).resolve())
        meta=by_path.get(source)
        if meta:
            vid=clean(meta.get("video_id"))
        else:
            stem=Path(source).stem
            vid=stem[:-5] if stem.endswith(".128k") else stem
            if vid not in by_video:
                # Last resort: find a video id that prefixes the source filename.
                vid=next((k for k in by_video if Path(source).name.startswith(k)),vid)
        if not vid:
            continue
        seg_by_video[vid].append({
            "start":float(r["start"]),"end":float(r["end"]),
            "local_speaker":clean(r["local_speaker"]),
            "global_speaker_id":clean(r["global_speaker_id"]),
            "overlap_flag":int(r["overlap"] or 0),
        })

    output_rows=[]
    for cap_path in sorted(normalized.glob("*.segments.jsonl")):
        vid=cap_path.name[:-len(".segments.jsonl")]
        segs=seg_by_video.get(vid,[])
        meta=by_video.get(vid,{})
        for cue_index,line in enumerate(cap_path.read_text(encoding="utf-8",errors="replace").splitlines()):
            if not line.strip():continue
            try:c=json.loads(line)
            except Exception:continue
            cs=float(c.get("start") or 0); ce=float(c.get("end") or cs)
            dur=max(0.001,ce-cs)
            by_spk=defaultdict(float)
            overlap_speech=0.0
            overlap_region=0.0
            contributing=set()
            for sg in segs:
                ov=overlap(cs,ce,sg["start"],sg["end"])
                if ov<=0:continue
                gid=sg["global_speaker_id"] or sg["local_speaker"]
                by_spk[gid]+=ov
                overlap_speech+=ov
                if sg["overlap_flag"]:
                    overlap_region+=ov
                contributing.add(gid)

            ranked=sorted(by_spk.items(),key=lambda x:(-x[1],x[0]))
            top_id=ranked[0][0] if ranked else ""
            top_sec=ranked[0][1] if ranked else 0.0
            # Summed diarization speech can exceed cue duration when overlap exists;
            # dominant share is based on speaker-overlap mass, coverage is bounded by cue duration.
            mass=sum(by_spk.values())
            dominant_share=(top_sec/mass) if mass>0 else 0.0
            coverage=min(1.0,mass/dur) if dur>0 else 0.0
            second_share=(ranked[1][1]/mass) if len(ranked)>1 and mass>0 else 0.0

            if not ranked or coverage<args.min_coverage:
                status="NO_SPEECH_MATCH"
            elif dominant_share>=args.high_dominant_share and second_share<=0.20:
                status="ATTRIBUTED_HIGH"
            elif dominant_share>=args.medium_dominant_share and second_share<=0.35:
                status="ATTRIBUTED_MEDIUM"
            else:
                status="AMBIGUOUS"

            rr=resolution.get(top_id,{})
            output_rows.append({
                "channel_id":args.channel_id,
                "video_id":vid,
                "canonical_url":clean(meta.get("url")),
                "title":clean(meta.get("title")),
                "cue_index":cue_index,
                "start_seconds":cs,
                "end_seconds":ce,
                "text":clean(c.get("text")),
                "raw_speaker_id":top_id,
                "acoustic_cluster_id":clean(rr.get("cluster_observation_id")),
                "canonical_voice_id":clean(rr.get("canonical_voice_id")),
                "resolved_entity_id":clean(rr.get("resolved_entity_id")),
                "speaker_display_name":clean(rr.get("display_name")),
                "speaker_resolution_status":clean(rr.get("binding_status") or rr.get("identity_status")),
                "speaker_resolution_confidence":clean(rr.get("confidence")),
                "speaker_attribution_status":status,
                "speaker_coverage_ratio":round(coverage,6),
                "dominant_speaker_share":round(dominant_share,6),
                "second_speaker_share":round(second_share,6),
                "speaker_count":len(contributing),
                "overlap_speech_seconds":round(overlap_region,6),
                "candidate_speakers_json":json.dumps(
                    [{"speaker_id":spk,"overlap_seconds":round(sec,6),"share":round(sec/mass,6) if mass else 0}
                     for spk,sec in ranked],ensure_ascii=False
                ),
                "caption_source_path":str(cap_path),
                "audio_sha256":clean(meta.get("sha256")),
            })

    fields=[
        "channel_id","video_id","canonical_url","title","cue_index","start_seconds","end_seconds","text",
        "raw_speaker_id","acoustic_cluster_id","canonical_voice_id","resolved_entity_id","speaker_display_name",
        "speaker_resolution_status","speaker_resolution_confidence","speaker_attribution_status",
        "speaker_coverage_ratio","dominant_speaker_share","second_speaker_share","speaker_count",
        "overlap_speech_seconds","candidate_speakers_json","caption_source_path","audio_sha256"
    ]
    csv_path=out/"caption_speaker_attribution.csv"
    with csv_path.open("w",newline="",encoding="utf-8-sig") as f:
        w=csv.DictWriter(f,fieldnames=fields); w.writeheader(); w.writerows(output_rows)
    jsonl_path=out/"caption_speaker_attribution.jsonl"
    with jsonl_path.open("w",encoding="utf-8") as f:
        for r in output_rows:f.write(json.dumps(r,ensure_ascii=False)+"\n")

    counts=defaultdict(int)
    for r in output_rows:counts[r["speaker_attribution_status"]]+=1
    summary={
        "channel_id":args.channel_id,
        "moji_output":str(moji),
        "normalized_dir":str(normalized),
        "audio_manifest":str(manifest),
        "row_count":len(output_rows),
        "status_counts":dict(counts),
        "csv":str(csv_path),"jsonl":str(jsonl_path),
    }
    (out/"caption_speaker_attribution_manifest.json").write_text(json.dumps(summary,indent=2),encoding="utf-8")
    print(json.dumps(summary,indent=2))
    return 0

if __name__=="__main__":
    raise SystemExit(main())
