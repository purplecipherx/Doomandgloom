#!/usr/bin/env python3
from __future__ import annotations
import argparse, json, sqlite3
from datetime import datetime, timezone
from pathlib import Path

def now():
    return datetime.now(timezone.utc).isoformat()

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--db",default="research/runtime/pipeline_jobs.sqlite")
    args=ap.parse_args()
    db=Path(args.db).resolve()
    c=sqlite3.connect(db,timeout=30)
    c.row_factory=sqlite3.Row
    ts=now()
    leased=c.execute("SELECT * FROM jobs WHERE lane='gpu' AND state='leased'").fetchall()
    for r in leased:
        c.execute(
            """UPDATE jobs
               SET state='queued', leased_by=NULL, lease_until=NULL, available_at=?,
                   updated_at=?, started_at=NULL,
                   attempts=CASE WHEN attempts>0 THEN attempts-1 ELSE 0 END
               WHERE id=?""",
            (ts,ts,r["id"])
        )
        c.execute(
            "INSERT INTO job_events(job_id,ts,worker,event_type,detail_json) VALUES(?,?,?,?,?)",
            (r["id"],ts,r["leased_by"] or "","manual_gpu_recovery",
             json.dumps({"job_key":r["job_key"],"kind":r["kind"]},ensure_ascii=False))
        )
    c.commit()
    print(json.dumps({
        "database":str(db),
        "requeued_leased_gpu_jobs":len(leased),
        "job_ids":[r["id"] for r in leased],
        "job_keys":[r["job_key"] for r in leased],
    },indent=2))
    c.close()
    return 0

if __name__=="__main__":
    raise SystemExit(main())
