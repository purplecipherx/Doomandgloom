#!/usr/bin/env python3
from __future__ import annotations
import argparse, json, urllib.request

def get_json(url):
    with urllib.request.urlopen(url, timeout=10) as r:
        return json.loads(r.read().decode("utf-8"))

def post_json(url, obj):
    data=json.dumps(obj).encode("utf-8")
    req=urllib.request.Request(url,data=data,headers={"Content-Type":"application/json"},method="POST")
    with urllib.request.urlopen(req,timeout=10) as r:
        return json.loads(r.read().decode("utf-8"))

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--hub",default="http://127.0.0.1:8765")
    ap.add_argument("--job-id",type=int,default=0)
    ap.add_argument("--job-key",default="")
    args=ap.parse_args()

    failed=get_json(args.hub+"/jobs?state=failed&lane=gpu&limit=1000").get("jobs",[])
    matches=[j for j in failed if (args.job_id and int(j["id"])==args.job_id) or (args.job_key and j["job_key"]==args.job_key)]
    if len(matches)!=1:
        raise SystemExit(f"Expected exactly one failed GPU job, found {len(matches)}")
    j=matches[0]
    payload=json.loads(j["payload_json"])
    body={
        "kind":j["kind"],"lane":j["lane"],"payload":payload,"job_key":j["job_key"],
        "priority":int(j["priority"]),"max_attempts":int(j["max_attempts"]),"force":True,
    }
    out=post_json(args.hub+"/enqueue",body)
    print(json.dumps({"requeued":out.get("created",False),"id":j["id"],"job_key":j["job_key"]},indent=2))
    return 0

if __name__=="__main__":
    raise SystemExit(main())
