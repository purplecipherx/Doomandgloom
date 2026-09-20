#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import os
import socket
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from pipeline_client import complete, enqueue, fail, heartbeat, lease

WRITE_LOCK = threading.Lock()

def now():
    return datetime.now(timezone.utc).isoformat()

class State:
    def __init__(self):
        self.lock=threading.Lock()
        self.active={}
        self.completed=0
        self.failed=0
        self.started_at=now()

    def set_active(self, worker, job):
        with self.lock: self.active[worker]={"id":job["id"],"kind":job["kind"],"job_key":job["job_key"],"started_at":now()}
    def clear(self, worker, ok):
        with self.lock:
            self.active.pop(worker,None)
            if ok: self.completed+=1
            else: self.failed+=1
    def snapshot(self):
        with self.lock:
            return {"service":"cpu","started_at":self.started_at,"active":dict(self.active),"completed":self.completed,"failed":self.failed,"ts":now()}

class StatusAPI(BaseHTTPRequestHandler):
    state=None
    def log_message(self, fmt, *args): return
    def do_GET(self):
        if self.path not in ("/health","/status"):
            self.send_response(404); self.end_headers(); return
        obj=self.state.snapshot(); obj["ok"]=True
        data=json.dumps(obj).encode("utf-8")
        self.send_response(200); self.send_header("Content-Type","application/json"); self.send_header("Content-Length",str(len(data))); self.end_headers(); self.wfile.write(data)

def run_logged(cmd, log_path: Path, cwd: Path):
    log_path.parent.mkdir(parents=True,exist_ok=True)
    with log_path.open("a",encoding="utf-8",errors="replace") as log:
        log.write("\n=== "+now()+" ===\n"+" ".join(map(str,cmd))+"\n")
        log.flush()
        cp=subprocess.run(cmd,cwd=str(cwd),stdout=log,stderr=subprocess.STDOUT,text=True)
    return cp.returncode

class HeartbeatThread(threading.Thread):
    def __init__(self, hub, job_id, worker, seconds):
        super().__init__(daemon=True); self.hub=hub; self.job_id=job_id; self.worker=worker; self.seconds=seconds; self.stop_event=threading.Event()
    def run(self):
        interval=max(15,min(60,self.seconds//3))
        while not self.stop_event.wait(interval):
            try: heartbeat(self.hub,job_id=self.job_id,worker=self.worker,lease_seconds=self.seconds)
            except Exception: pass
    def stop(self): self.stop_event.set()

def ps(script: Path, pairs, switches=()):
    cmd=["powershell.exe","-ExecutionPolicy","Bypass","-File",str(script)]
    for k,v in pairs:
        if v is not None: cmd += [f"-{k}",str(v)]
    for sw in switches: cmd += [f"-{sw}"]
    return cmd

def queue_followups(hub, payload, phase):
    cid=payload["channel_id"]; gen=payload["generation"]
    base=dict(payload)
    enqueue(hub,kind="analysis_sync",lane="cpu",payload=base,job_key=f"analysis:{phase}:{cid}:{gen}",priority=60)
    enqueue(hub,kind="spider_channel",lane="cpu",payload=base,job_key=f"spider:{phase}:{cid}:{gen}",priority=80)

def handle_job(job, *, repo: Path, hub: str, audio_workers: int):
    payload=json.loads(job["payload_json"])
    kind=job["kind"]
    logs=repo/"research"/"runtime"/"logs"
    runner=repo/"scripts"/"run_youtube_channel_harvest.ps1"
    ytpy=repo/".venv-youtube"/"Scripts"/"python.exe"
    channel_root=repo/"research"/"youtube"/payload["name"]

    if kind=="harvest_channel":
        pairs=[
            ("Url",payload["url"]),("Name",payload["name"]),
            ("Workers",payload.get("caption_workers",8)),("Sleep",payload.get("sleep",0.75))
        ]
        if int(payload.get("limit_videos",0) or 0)>0: pairs.append(("Limit",payload["limit_videos"]))
        code=run_logged(ps(runner,pairs),logs/f"job_{job['id']}_harvest.log",repo)
        if code: raise RuntimeError(f"harvest exit code {code}")
        queue_followups(hub,payload,"captions")
        enqueue(hub,kind="prepare_audio",lane="cpu",payload=payload,job_key=f"audio:{payload['channel_id']}:{payload['generation']}",priority=40)
        return {"exit_code":0,"channel_root":str(channel_root)}

    if kind=="prepare_audio":
        queue=channel_root/"needs_transcription.csv"
        script=repo/"scripts"/"download_captionless_audio.py"
        cmd=[str(ytpy),str(script),str(queue),"--workers",str(payload.get("audio_workers",audio_workers))]
        if int(payload.get("captionless_limit",0) or 0)>0:
            cmd += ["--limit",str(payload["captionless_limit"])]
        code=run_logged(cmd,logs/f"job_{job['id']}_audio.log",repo)
        if code: raise RuntimeError(f"audio prefetch exit code {code}")
        manifest=channel_root/"audio_fallback"/"audio_manifest.jsonl"
        ready=0
        if manifest.exists():
            for line in manifest.read_text(encoding="utf-8",errors="replace").splitlines():
                try:
                    r=json.loads(line)
                    if r.get("status") in ("downloaded","cached") and r.get("audio_path"): ready+=1
                except Exception: pass
        if ready:
            enqueue(hub,kind="gpu_moji_channel",lane="gpu",payload=payload,job_key=f"gpu:{payload['channel_id']}:{payload['generation']}",priority=20,max_attempts=2)
        return {"exit_code":0,"audio_ready":ready}

    if kind=="analysis_sync":
        script=repo/"scripts"/"build_research_ledger.py"
        with WRITE_LOCK:
            code=run_logged([str(ytpy),str(script),"--research-root",str(channel_root),"--output-dir",str(repo/"data"/"analysis")],
                            logs/f"job_{job['id']}_analysis.log",repo)
            if code: raise RuntimeError(f"analysis ledger exit code {code}")
            review_script=repo/"scripts"/"queue_semantic_review.py"
            review_code=run_logged([
                str(ytpy),str(review_script),
                "--ledger",str(repo/"data"/"analysis"/"transcript_units.csv"),
                "--output-dir",str(repo/"data"/"analysis"/"review_batches"),
                "--batch-size","40","--hub",hub
            ],logs/f"job_{job['id']}_review_queue.log",repo)
            if review_code: raise RuntimeError(f"semantic review queue exit code {review_code}")
        return {"exit_code":0,"ledger":str(repo/"data"/"analysis"/"transcript_units.csv")}

    if kind=="spider_channel":
        script=repo/"scripts"/"run_transcript_spider.ps1"
        batch=f"{payload['generation']}_{payload['channel_id']}_{job['id']}"
        with WRITE_LOCK:
            code=run_logged(ps(script,[("ResearchRoot",channel_root),("BatchId",batch),("SourceLabel",payload["channel_id"])]),
                            logs/f"job_{job['id']}_spider.log",repo)
        if code: raise RuntimeError(f"spider exit code {code}")
        return {"exit_code":0,"batch_id":batch}

    raise RuntimeError(f"unsupported CPU job kind: {kind}")

def worker_loop(index, args, repo, state):
    worker=f"{socket.gethostname()}-cpu-{index}"
    kinds=["harvest_channel","prepare_audio","analysis_sync","spider_channel"]
    while True:
        try:
            job=lease(args.hub,lane="cpu",worker=worker,kinds=kinds,lease_seconds=args.lease_seconds)
        except Exception:
            time.sleep(args.poll); continue
        if not job:
            time.sleep(args.poll); continue
        state.set_active(worker,job)
        hb=HeartbeatThread(args.hub,job["id"],worker,args.lease_seconds); hb.start()
        ok=False
        try:
            result=handle_job(job,repo=repo,hub=args.hub,audio_workers=args.audio_workers)
            complete(args.hub,job_id=job["id"],worker=worker,result=result); ok=True
        except Exception as e:
            try: fail(args.hub,job_id=job["id"],worker=worker,error=repr(e),retry_delay=30)
            except Exception: pass
        finally:
            hb.stop(); state.clear(worker,ok)

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--hub",default="http://127.0.0.1:8765")
    ap.add_argument("--host",default="127.0.0.1")
    ap.add_argument("--port",type=int,default=8766)
    ap.add_argument("--workers",type=int,default=4)
    ap.add_argument("--audio-workers",type=int,default=4)
    ap.add_argument("--poll",type=float,default=1.0)
    ap.add_argument("--lease-seconds",type=int,default=1800)
    args=ap.parse_args()
    repo=Path(__file__).resolve().parents[1]
    state=State(); StatusAPI.state=state
    server=ThreadingHTTPServer((args.host,args.port),StatusAPI)
    threading.Thread(target=server.serve_forever,daemon=True).start()
    print(f"CPU pipeline service http://{args.host}:{args.port} workers={args.workers} hub={args.hub}")
    with ThreadPoolExecutor(max_workers=max(1,args.workers)) as ex:
        for i in range(max(1,args.workers)): ex.submit(worker_loop,i+1,args,repo,state)
        try:
            while True: time.sleep(3600)
        except KeyboardInterrupt: pass
    server.shutdown(); return 0

if __name__=="__main__":
    raise SystemExit(main())
