#!/usr/bin/env python3
from __future__ import annotations

import json
import tempfile
from pathlib import Path

from pipeline_hub import JobDB

def main():
    with tempfile.TemporaryDirectory(prefix="doomandgloom_hubtest_") as td:
        db=JobDB(Path(td)/"jobs.sqlite")
        row,created=db.enqueue("test_cpu","cpu",{"x":1},"selftest:1",priority=1,max_attempts=2)
        assert created and row["state"]=="queued"
        job=db.lease("cpu","selftest-worker",["test_cpu"],lease_seconds=60)
        assert job and job["job_key"]=="selftest:1" and job["state"]=="leased"
        ok,until=db.heartbeat(job["id"],"selftest-worker",lease_seconds=60)
        assert ok and until
        assert db.complete(job["id"],"selftest-worker",{"ok":True})
        done=db.list_jobs(state="done",limit=10)
        assert len(done)==1 and done[0]["job_key"]=="selftest:1"
        stats=db.stats()
        assert stats["lanes"]["cpu"]["done"]==1
        print(json.dumps({"ok":True,"stats":stats},indent=2))
    return 0

if __name__=="__main__":
    raise SystemExit(main())
