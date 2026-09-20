#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import re
from datetime import datetime, timezone
from pathlib import Path

from pipeline_client import enqueue

def safe(s):
    return re.sub(r"[^A-Za-z0-9._-]","_",s or "youtube_source")

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--hub",default="http://127.0.0.1:8765")
    ap.add_argument("--registry",default="data/youtube_channels.csv")
    ap.add_argument("--run-id",default="")
    ap.add_argument("--limit-channels",type=int,default=0)
    ap.add_argument("--limit-videos",type=int,default=0)
    ap.add_argument("--captionless-limit",type=int,default=0)
    ap.add_argument("--voice-index-limit",type=int,default=0)
    ap.add_argument("--caption-workers",type=int,default=8)
    ap.add_argument("--audio-workers",type=int,default=4)
    ap.add_argument("--audio-batch-size",type=int,default=25)
    ap.add_argument("--sleep",type=float,default=0.75)
    ap.add_argument("--device",choices=["cuda","cpu"],default="cuda")
    ap.add_argument("--whisper-model",default="medium.en")
    ap.add_argument("--compute-type",default="int8")
    ap.add_argument("--batch-size",type=int,default=4)
    ap.add_argument("--force",action="store_true")
    ap.add_argument("--force-whisper-all",action="store_true")
    args=ap.parse_args()

    repo=Path(__file__).resolve().parents[1]
    rows=list(csv.DictReader((repo/args.registry).open(encoding="utf-8-sig")))
    channels=[r for r in rows if (r.get("enabled") or "").strip().lower()=="true"
              and (r.get("verification_status") or "").strip().lower()=="verified"]
    if args.limit_channels>0:
        channels=channels[:args.limit_channels]
    run_id=args.run_id or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    made=0
    for ch in channels:
        cid=(ch.get("channel_id") or "").strip()
        payload={
            "generation":run_id,
            "channel_id":cid,
            "entity_id":(ch.get("entity_id") or "").strip(),
            "channel_name":ch.get("channel_name",""),
            "url":ch.get("youtube_url",""),
            "name":safe(cid),
            "caption_workers":args.caption_workers,
            "audio_workers":args.audio_workers,
            "audio_batch_size":args.audio_batch_size,
            "sleep":args.sleep,
            "limit_videos":args.limit_videos,
            "captionless_limit":args.captionless_limit,
            "voice_index_limit":args.voice_index_limit,
            "device":args.device,
            "whisper_model":args.whisper_model,
            "compute_type":args.compute_type,
            "batch_size":args.batch_size,
            "force_whisper_all":args.force_whisper_all,
        }
        r=enqueue(args.hub,kind="harvest_channel",lane="cpu",payload=payload,
                  job_key=f"harvest:{cid}:{run_id}",priority=10,max_attempts=3,force=args.force)
        if r.get("created"):
            made+=1
        print(f"{cid}: {'queued' if r.get('created') else 'already exists'}")
    print(f"Run {run_id}: {made} new harvest job(s), {len(channels)} channel(s) selected.")
    return 0

if __name__=="__main__":
    raise SystemExit(main())
