#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import subprocess
from pathlib import Path

def clean(x): return str(x or "").strip()

def sha256_file(path:Path):
    h=hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda:f.read(1024*1024),b""):
            h.update(chunk)
    return h.hexdigest()

def resolve_audio_path(manifest:Path, rel:str):
    p=Path(rel)
    if p.is_absolute(): return p.resolve()
    candidates=[(manifest.parent/p).resolve(),(manifest.parent.parent/p).resolve()]
    return next((x for x in candidates if x.exists()),candidates[0])

def load_audio_manifest(path:Path):
    out={}
    for line in path.read_text(encoding="utf-8",errors="replace").splitlines():
        if not line.strip(): continue
        try:r=json.loads(line)
        except Exception: continue
        if clean(r.get("status")) not in {"downloaded","cached"}: continue
        vid=clean(r.get("video_id")); ap=clean(r.get("audio_path"))
        if not vid or not ap: continue
        p=resolve_audio_path(path,ap)
        if p.exists(): out[vid]=(r,p)
    return out

def load_cues(path:Path):
    cues=[]
    if not path.exists(): return cues
    for idx,line in enumerate(path.read_text(encoding="utf-8",errors="replace").splitlines()):
        if not line.strip(): continue
        try:c=json.loads(line)
        except Exception: continue
        start=float(c.get("start") or 0); end=float(c.get("end") or start)
        text=clean(c.get("text"))
        if end>start and text:
            cues.append({"cue_index":idx,"start":start,"end":end,"text":text})
    return cues

def choose_cues(cues, interval, min_cue_sec, min_words, max_samples):
    eligible=[c for c in cues if (c["end"]-c["start"])>=min_cue_sec and len(c["text"].split())>=min_words]
    if not eligible: return []
    duration=max(c["end"] for c in cues)
    targets=[]
    t=min(interval/2.0,max(0.0,duration/2.0))
    while t<=duration and len(targets)<max_samples:
        targets.append(t); t+=interval
    if not targets: targets=[(eligible[0]["start"]+eligible[-1]["end"])/2.0]
    chosen=[]; seen=set()
    for target in targets:
        c=min(eligible,key=lambda x:abs(((x["start"]+x["end"])/2.0)-target))
        if c["cue_index"] in seen: continue
        seen.add(c["cue_index"]); chosen.append(c)
    # Ensure some coverage at beginning/end for long videos.
    for c in (eligible[0],eligible[-1]):
        if len(chosen)>=max_samples: break
        if c["cue_index"] not in seen:
            seen.add(c["cue_index"]); chosen.append(c)
    return sorted(chosen,key=lambda x:x["start"])[:max_samples]

def extract(source:Path,start:float,end:float,target:Path):
    target.parent.mkdir(parents=True,exist_ok=True)
    cp=subprocess.run([
        "ffmpeg","-hide_banner","-loglevel","error","-y",
        "-ss",f"{start:.3f}","-i",str(source),"-t",f"{max(0.05,end-start):.3f}",
        "-vn","-ac","1","-ar","16000","-c:a","flac",str(target)
    ],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
    if cp.returncode:
        raise RuntimeError(cp.stderr.strip() or f"ffmpeg failed: {source}")

def main():
    ap=argparse.ArgumentParser(description="Extract sparse caption-guided voice samples for cheap speaker matching.")
    ap.add_argument("--normalized-dir",required=True)
    ap.add_argument("--audio-manifest",required=True)
    ap.add_argument("--output",required=True)
    ap.add_argument("--interval-seconds",type=float,default=90.0)
    ap.add_argument("--clip-seconds",type=float,default=3.0)
    ap.add_argument("--min-cue-seconds",type=float,default=1.8)
    ap.add_argument("--min-words",type=int,default=3)
    ap.add_argument("--max-samples-per-video",type=int,default=80)
    args=ap.parse_args()

    normalized=Path(args.normalized_dir).resolve()
    manifest=Path(args.audio_manifest).resolve()
    out=Path(args.output).resolve(); clips=out/"clips"; clips.mkdir(parents=True,exist_ok=True)
    audio=load_audio_manifest(manifest)
    rows=[]

    for vid,(meta,source) in sorted(audio.items()):
        cues=load_cues(normalized/f"{vid}.segments.jsonl")
        selected=choose_cues(cues,args.interval_seconds,args.min_cue_seconds,args.min_words,args.max_samples_per_video)
        for ordinal,c in enumerate(selected,1):
            cue_start, cue_end=c["start"],c["end"]
            cue_dur=cue_end-cue_start
            use=min(float(args.clip_seconds),cue_dur)
            mid=(cue_start+cue_end)/2.0
            start=max(cue_start,mid-use/2.0); end=min(cue_end,start+use)
            if end-start<args.min_cue_seconds: continue
            sid=f"{vid}__C{int(c['cue_index']):06d}"
            target=clips/vid/f"{sid}.flac"
            if not target.exists(): extract(source,start,end,target)
            rows.append({
                "sample_id":sid,"video_id":vid,"sample_ordinal":ordinal,
                "cue_index":c["cue_index"],"start_seconds":round(start,3),"end_seconds":round(end,3),
                "duration_seconds":round(end-start,3),"text":c["text"],
                "source_audio_path":str(source),"source_audio_sha256":clean(meta.get("sha256")),
                "source_url":clean(meta.get("url")),"title":clean(meta.get("title")),
                "clip_path":str(target),"clip_sha256":sha256_file(target),
            })

    jl=out/"sample_manifest.jsonl"
    with jl.open("w",encoding="utf-8") as f:
        for r in rows:f.write(json.dumps(r,ensure_ascii=False)+"\n")
    fields=list(rows[0].keys()) if rows else [
        "sample_id","video_id","sample_ordinal","cue_index","start_seconds","end_seconds","duration_seconds",
        "text","source_audio_path","source_audio_sha256","source_url","title","clip_path","clip_sha256"
    ]
    with (out/"sample_manifest.csv").open("w",newline="",encoding="utf-8-sig") as f:
        w=csv.DictWriter(f,fieldnames=fields); w.writeheader(); w.writerows(rows)
    total=sum(float(r["duration_seconds"]) for r in rows)
    summary={
        "videos_with_audio":len(audio),"sample_count":len(rows),"sample_audio_seconds":round(total,3),
        "interval_seconds":args.interval_seconds,"clip_seconds":args.clip_seconds,
        "sample_manifest":str(jl),"clips_dir":str(clips)
    }
    (out/"sample_summary.json").write_text(json.dumps(summary,indent=2),encoding="utf-8")
    print(json.dumps(summary,indent=2))
    return 0

if __name__=="__main__":
    raise SystemExit(main())
