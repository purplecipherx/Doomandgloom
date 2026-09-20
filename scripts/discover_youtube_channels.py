#!/usr/bin/env python3
"""
Discover candidate YouTube channels for every entity in data/entities.csv.
This does NOT auto-approve channels. It writes candidates for review.
"""
from __future__ import annotations
import argparse, csv, json, re, subprocess, sys
from difflib import SequenceMatcher
from pathlib import Path

def yt(args, timeout=120):
    return subprocess.run(
        [sys.executable,"-m","yt_dlp",*args],
        text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        encoding="utf-8", errors="replace", timeout=timeout
    )

def norm(s):
    s=(s or "").lower()
    s=re.sub(r"[^a-z0-9]+"," ",s)
    return " ".join(s.split())

def score(a,b):
    return SequenceMatcher(None,norm(a),norm(b)).ratio()

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--entities",default="data/entities.csv")
    ap.add_argument("--output",default="data/youtube_channel_candidates.csv")
    ap.add_argument("--results-per-entity",type=int,default=5)
    args=ap.parse_args()

    entities=list(csv.DictReader(open(args.entities,encoding="utf-8-sig")))
    rows=[]
    seen=set()

    for i,e in enumerate(entities,1):
        name=e.get("name","").strip()
        eid=e.get("id","").strip()
        if not name:
            continue
        q=f'ytsearch{args.results_per_entity}:{name}'
        p=yt(["--flat-playlist","--dump-json","--ignore-errors","--no-warnings",q])
        candidates={}
        for line in p.stdout.splitlines():
            try: o=json.loads(line)
            except Exception: continue
            cid=o.get("channel_id") or ""
            cname=o.get("channel") or o.get("uploader") or ""
            curl=o.get("channel_url") or (f"https://www.youtube.com/channel/{cid}" if cid else "")
            if not cid and not curl:
                continue
            key=cid or curl
            rec=candidates.get(key)
            sim=score(name,cname)
            if rec is None or sim>rec["name_similarity"]:
                candidates[key]={
                    "entity_id":eid,
                    "entity_name":name,
                    "candidate_channel_id":cid,
                    "candidate_channel_name":cname,
                    "candidate_channel_url":curl,
                    "name_similarity":round(sim,4),
                    "example_video_id":o.get("id",""),
                    "example_title":o.get("title",""),
                    "verification_status":"candidate",
                    "discovery_query":name,
                }
        for rec in sorted(candidates.values(), key=lambda x:x["name_similarity"], reverse=True):
            key=(eid,rec["candidate_channel_id"] or rec["candidate_channel_url"])
            if key not in seen:
                seen.add(key); rows.append(rec)
        print(f"[{i}/{len(entities)}] {name}: {len(candidates)} candidate channel(s)",flush=True)

    fields=[
        "entity_id","entity_name","candidate_channel_id","candidate_channel_name",
        "candidate_channel_url","name_similarity","example_video_id","example_title",
        "verification_status","discovery_query"
    ]
    out=Path(args.output); out.parent.mkdir(parents=True,exist_ok=True)
    with out.open("w",newline="",encoding="utf-8-sig") as f:
        w=csv.DictWriter(f,fieldnames=fields); w.writeheader(); w.writerows(rows)
    print(f"Wrote {len(rows)} candidate channels -> {out}")

if __name__=="__main__":
    main()
