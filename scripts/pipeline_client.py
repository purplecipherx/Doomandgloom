from __future__ import annotations

import json
import urllib.request

def request_json(base_url: str, path: str, payload=None, timeout=30):
    url=base_url.rstrip("/") + path
    data=None
    headers={}
    if payload is not None:
        data=json.dumps(payload,ensure_ascii=False).encode("utf-8")
        headers["Content-Type"]="application/json"
    req=urllib.request.Request(url,data=data,headers=headers,method="POST" if payload is not None else "GET")
    with urllib.request.urlopen(req,timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))

def enqueue(base_url, *, kind, lane, payload, job_key, priority=100, max_attempts=3, force=False):
    return request_json(base_url,"/enqueue",{
        "kind":kind,"lane":lane,"payload":payload,"job_key":job_key,
        "priority":priority,"max_attempts":max_attempts,"force":force
    })

def lease(base_url, *, lane, worker, kinds=None, lease_seconds=900):
    return request_json(base_url,"/lease",{
        "lane":lane,"worker":worker,"kinds":kinds,"lease_seconds":lease_seconds
    }).get("job")

def heartbeat(base_url, *, job_id, worker, lease_seconds=900):
    return request_json(base_url,"/heartbeat",{
        "job_id":job_id,"worker":worker,"lease_seconds":lease_seconds
    })

def complete(base_url, *, job_id, worker, result=None):
    return request_json(base_url,"/complete",{
        "job_id":job_id,"worker":worker,"result":result or {}
    })

def fail(base_url, *, job_id, worker, error, retry_delay=30):
    return request_json(base_url,"/fail",{
        "job_id":job_id,"worker":worker,"error":str(error),"retry_delay":retry_delay
    })
