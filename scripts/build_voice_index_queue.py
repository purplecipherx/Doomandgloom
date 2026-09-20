#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
from pathlib import Path

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("caption_status_csv")
    ap.add_argument("--output",default="")
    ap.add_argument("--include-status",default="captioned")
    args=ap.parse_args()

    src=Path(args.caption_status_csv).resolve()
    out=Path(args.output).resolve() if args.output else src.parent/"voice_index_queue.csv"
    statuses={x.strip() for x in args.include_status.split(",") if x.strip()}
    rows=[]
    for r in csv.DictReader(src.open(encoding="utf-8-sig")):
        if (r.get("status") or "").strip() not in statuses:
            continue
        if not (r.get("video_id") and r.get("url")):
            continue
        rows.append({
            "video_id":r.get("video_id",""),
            "url":r.get("url",""),
            "title":r.get("title",""),
            "channel_name":r.get("channel_name",""),
            "reason":"voice_index",
        })
    out.parent.mkdir(parents=True,exist_ok=True)
    with out.open("w",newline="",encoding="utf-8-sig") as f:
        fields=["video_id","url","title","channel_name","reason"]
        w=csv.DictWriter(f,fieldnames=fields); w.writeheader(); w.writerows(rows)
    print(f"{len(rows)} captioned item(s) -> {out}")
    return 0

if __name__=="__main__":
    raise SystemExit(main())
