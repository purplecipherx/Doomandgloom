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

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--ledger",default="data/analysis/transcript_units.csv")
    ap.add_argument("--output-dir",default="data/analysis/review_batches")
    ap.add_argument("--batch-size",type=int,default=40)
    ap.add_argument("--hub",default="")
    args=ap.parse_args()

    ledger=Path(args.ledger).resolve()
    out=Path(args.output_dir).resolve()
    pending_dir=out/"pending"; pending_dir.mkdir(parents=True,exist_ok=True)
    index_path=out/"review_batch_index.csv"
    index=load_index(index_path)

    rows=list(csv.DictReader(ledger.open(encoding="utf-8-sig")))
    current_rows=[r for r in rows if r.get("source_status","CURRENT")=="CURRENT"]
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
            neighbor_map[r["unit_id"]]={
                "context_before":[x["text"] for x in content_rows[max(0,idx-2):idx]],
                "context_after":[x["text"] for x in content_rows[idx+1:idx+3]],
            }

    pending=[r for r in current_rows if r.get("semantic_review_status")!="COMPLETE" and r["unit_id"] not in index]

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
                rec={
                    "batch_id":bid,
                    "unit_id":r["unit_id"],
                    "content_id":r["content_id"],
                    "source_type":r["source_type"],
                    "source_path":r["source_path"],
                    "start_seconds":r["start_seconds"],
                    "end_seconds":r["end_seconds"],
                    "speaker_id":r["speaker_id"],
                    "text":r["text"],
                    "context_before":neighbor_map.get(r["unit_id"],{}).get("context_before",[]),
                    "context_after":neighbor_map.get(r["unit_id"],{}).get("context_after",[]),
                    "review_required":{
                        "classify_speech_act":True,
                        "extract_all_mentions":True,
                        "extract_atomic_claims":True,
                        "extract_claims_about_people_or_orgs":True,
                        "extract_stances":True,
                        "extract_relationships":True,
                        "extract_products_services_sponsors_ctas":True,
                        "extract_predictions":True,
                        "extract_money_conflict_signals":True,
                        "extract_citations_sources_mentioned":True,
                        "fact_check_every_atomic_factual_claim":True
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
              "total_indexed_units":len(index),"hub":args.hub or None}
    (out/"review_queue_manifest.json").write_text(json.dumps(manifest,indent=2),encoding="utf-8")
    print(json.dumps(manifest,indent=2))
    return 0

if __name__=="__main__":
    raise SystemExit(main())
