#!/usr/bin/env python3
from __future__ import annotations

import argparse, json, re
from collections import Counter, defaultdict
from pathlib import Path

PATTERNS=[
    ("HTTP_403", re.compile(r"HTTP Error 403|HTTP 403|403 Forbidden", re.I)),
    ("PO_TOKEN", re.compile(r"PO Token|Proof of Origin|pot", re.I)),
    ("ONLY_IMAGES", re.compile(r"Only images are available|only images", re.I)),
    ("NO_FORMAT", re.compile(r"Requested format is not available|No video formats found|no formats", re.I)),
    ("SIGN_IN", re.compile(r"Sign in to confirm|login required|age-restricted", re.I)),
    ("RATE_LIMIT", re.compile(r"429|Too Many Requests|rate limit", re.I)),
    ("FRAGMENT_FAIL", re.compile(r"fragment|Unable to download video data|failed to download", re.I)),
    ("FFMPEG", re.compile(r"ffmpeg|Invalid data found|Error while decoding", re.I)),
]

def classify(text):
    for name,rx in PATTERNS:
        if rx.search(text or ""):
            return name
    return "OTHER"

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("root", nargs="+")
    ap.add_argument("--examples", type=int, default=5)
    args=ap.parse_args()

    counts=Counter(); examples=defaultdict(list); total=0; failed=0
    for root in args.root:
        for p in Path(root).rglob("audio_manifest.json"):
            total+=1
            try:r=json.loads(p.read_text(encoding="utf-8",errors="replace"))
            except Exception:continue
            if r.get("status") in {"downloaded","cached"}:
                continue
            failed+=1
            text=(r.get("stderr_tail") or "")+"\n"+(r.get("ffmpeg_error") or "")
            kind=classify(text)
            counts[kind]+=1
            if len(examples[kind])<args.examples:
                examples[kind].append({
                    "video_id":r.get("video_id",""),
                    "mode":r.get("acquisition_mode",""),
                    "stderr_tail":(r.get("stderr_tail") or "")[-900:],
                    "ffmpeg_error":r.get("ffmpeg_error",""),
                    "path":str(p),
                })
    print(json.dumps({
        "manifests":total,"failed":failed,"failure_classes":counts,
        "examples":examples
    },indent=2,ensure_ascii=False))
    return 0

if __name__=="__main__":
    raise SystemExit(main())
