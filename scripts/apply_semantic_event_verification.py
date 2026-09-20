#!/usr/bin/env python3
from __future__ import annotations

import argparse,csv,json
from datetime import datetime,timezone
from pathlib import Path

ALLOWED={"VERIFIED_TEXT","NEEDS_REVIEW","REJECTED_TEXT"}

def now():
    return datetime.now(timezone.utc).isoformat()

def read_csv(path):
    p=Path(path)
    if not p.exists(): return []
    return list(csv.DictReader(p.open(encoding="utf-8-sig")))

def write_csv(path,rows,fields):
    p=Path(path); p.parent.mkdir(parents=True,exist_ok=True)
    with p.open("w",newline="",encoding="utf-8-sig") as f:
        w=csv.DictWriter(f,fieldnames=fields); w.writeheader()
        for r in rows:w.writerow({k:r.get(k,"") for k in fields})

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("verification_jsonl")
    ap.add_argument("--events",default="data/analysis/semantic_events.csv")
    ap.add_argument("--output",default="data/analysis/semantic_event_verifications.csv")
    args=ap.parse_args()

    events=read_csv(args.events)
    by_id={r.get("semantic_event_id",""):r for r in events}
    existing={r.get("semantic_event_id",""):r for r in read_csv(args.output)}
    accepted=0
    for line_no,line in enumerate(Path(args.verification_jsonl).read_text(encoding="utf-8").splitlines(),1):
        if not line.strip():continue
        r=json.loads(line)
        eid=r.get("semantic_event_id","")
        if eid not in by_id:
            raise SystemExit(f"line {line_no}: unknown semantic_event_id {eid}")
        status=(r.get("status") or "").upper()
        if status not in ALLOWED:
            raise SystemExit(f"line {line_no}: invalid status {status}")
        existing[eid]={
            "semantic_event_id":eid,
            "status":status,
            "error_types_json":json.dumps(r.get("error_types") or [],ensure_ascii=False),
            "reviewer":r.get("reviewer",""),
            "reviewed_at":r.get("reviewed_at") or now(),
            "reasoning_summary":r.get("reasoning_summary",""),
            "corrected_predicate_code":r.get("corrected_predicate_code",""),
            "corrected_target_entity_id":r.get("corrected_target_entity_id",""),
            "corrected_target_surface":r.get("corrected_target_surface",""),
            "notes":r.get("notes",""),
        }
        accepted+=1
    fields=[
        "semantic_event_id","status","error_types_json","reviewer","reviewed_at","reasoning_summary",
        "corrected_predicate_code","corrected_target_entity_id","corrected_target_surface","notes"
    ]
    rows=sorted(existing.values(),key=lambda r:r["semantic_event_id"])
    write_csv(args.output,rows,fields)
    print(json.dumps({"accepted":accepted,"total_verifications":len(rows)},indent=2))
    return 0

if __name__=="__main__":
    raise SystemExit(main())
