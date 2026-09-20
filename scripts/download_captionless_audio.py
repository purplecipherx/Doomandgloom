#!/usr/bin/env python3
"""
Download AUDIO ONLY for rows in needs_transcription.csv.
Never downloads a video stream.
"""
from __future__ import annotations
import argparse, csv, hashlib, json, subprocess, sys
from datetime import datetime, timezone
from pathlib import Path

def now():
    return datetime.now(timezone.utc).isoformat()

def run(args, timeout=1800):
    return subprocess.run(
        [sys.executable, "-m", "yt_dlp", *args],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
    )

def ytdlp_version():
    p=run(["--version"], timeout=30)
    return p.stdout.strip() if p.returncode==0 else "unknown"

def sha256(path: Path):
    h=hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda:f.read(1024*1024), b""):
            h.update(chunk)
    return h.hexdigest()

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("queue_csv")
    ap.add_argument("--output-dir", default="")
    ap.add_argument("--limit", type=int, default=0)
    args=ap.parse_args()

    queue=Path(args.queue_csv).resolve()
    base=Path(args.output_dir).resolve() if args.output_dir else queue.parent/"audio_fallback"
    base.mkdir(parents=True, exist_ok=True)

    rows=list(csv.DictReader(queue.open(encoding="utf-8-sig")))
    if args.limit>0: rows=rows[:args.limit]

    run_record={
        "run_id": datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")+"_audio_fallback",
        "started_at": now(),
        "queue_csv": str(queue),
        "output_dir": str(base),
        "python_version": sys.version,
        "yt_dlp_version": ytdlp_version(),
        "argv": sys.argv,
        "queued_count": len(rows),
        "format_rule": "bestaudio only; no video fallback"
    }
    (base/"run_manifest.json").write_text(json.dumps(run_record,indent=2),encoding="utf-8")

    manifest=[]
    for i,row in enumerate(rows,1):
        vid=row["video_id"]; url=row["url"]
        vdir=base/vid; vdir.mkdir(parents=True, exist_ok=True)
        outtmpl=str(vdir/"%(id)s.%(ext)s")
        p=run([
            "--no-playlist",
            "-f","bestaudio",
            "--write-info-json",
            "--no-write-comments",
            "-o",outtmpl,
            url
        ])
        files=[x for x in vdir.iterdir() if x.is_file() and x.suffix.lower() not in (".json",".jpg",".jpeg",".png",".webp",".part",".ytdl")]
        if files:
            audio=max(files,key=lambda x:x.stat().st_size)
            status="downloaded"
            digest=sha256(audio)
            rel=str(audio.relative_to(queue.parent))
        else:
            status="failed"
            digest=""
            rel=""
        rec={
            "video_id":vid,
            "url":url,
            "title":row.get("title",""),
            "downloaded_at":now(),
            "status":status,
            "audio_path":rel,
            "sha256":digest,
            "stderr_tail":p.stderr[-1000:]
        }
        manifest.append(rec)
        (vdir/"audio_manifest.json").write_text(json.dumps(rec,indent=2),encoding="utf-8")
        print(f"[audio] {i}/{len(rows)} {vid}: {status}",flush=True)

    with (base/"audio_manifest.jsonl").open("w",encoding="utf-8") as f:
        for r in manifest:
            f.write(json.dumps(r,ensure_ascii=False)+"\n")
    run_record["completed_at"]=now()
    run_record["status"]="complete"
    run_record["downloaded_count"]=sum(1 for r in manifest if r["status"]=="downloaded")
    run_record["failed_count"]=sum(1 for r in manifest if r["status"]=="failed")
    (base/"run_manifest.json").write_text(json.dumps(run_record,indent=2),encoding="utf-8")

if __name__=="__main__":
    main()
