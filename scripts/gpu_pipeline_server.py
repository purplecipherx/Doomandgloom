#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import socket
import subprocess
import threading
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from pipeline_client import complete, enqueue, fail, heartbeat, lease

def now():
    return datetime.now(timezone.utc).isoformat()

class State:
    def __init__(self):
        self.lock=threading.Lock()
        self.active=None
        self.completed=0
        self.failed=0
        self.started_at=now()
    def set_active(self,job):
        with self.lock:
            self.active={"id":job["id"],"kind":job["kind"],"job_key":job["job_key"],"started_at":now()}
    def clear(self,ok):
        with self.lock:
            self.active=None
            if ok:self.completed+=1
            else:self.failed+=1
    def snapshot(self):
        with self.lock:
            return {"service":"gpu","started_at":self.started_at,"active":self.active,"completed":self.completed,"failed":self.failed,"ts":now()}

class StatusAPI(BaseHTTPRequestHandler):
    state=None
    def log_message(self,fmt,*args): return
    def do_GET(self):
        if self.path not in ("/health","/status"):
            self.send_response(404); self.end_headers(); return
        obj=self.state.snapshot(); obj["ok"]=True
        data=json.dumps(obj).encode("utf-8")
        self.send_response(200); self.send_header("Content-Type","application/json"); self.send_header("Content-Length",str(len(data))); self.end_headers(); self.wfile.write(data)

class HeartbeatThread(threading.Thread):
    def __init__(self,hub,job_id,worker,seconds):
        super().__init__(daemon=True); self.hub=hub; self.job_id=job_id; self.worker=worker; self.seconds=seconds; self.stop_event=threading.Event()
    def run(self):
        interval=max(20,min(90,self.seconds//3))
        while not self.stop_event.wait(interval):
            try: heartbeat(self.hub,job_id=self.job_id,worker=self.worker,lease_seconds=self.seconds)
            except Exception: pass
    def stop(self): self.stop_event.set()

def ps(script: Path,pairs,switches=()):
    cmd=["powershell.exe","-ExecutionPolicy","Bypass","-File",str(script)]
    for k,v in pairs:
        if v is not None: cmd += [f"-{k}",str(v)]
    for sw in switches: cmd += [f"-{sw}"]
    return cmd

def run_logged(cmd,log_path:Path,cwd:Path):
    log_path.parent.mkdir(parents=True,exist_ok=True)
    with log_path.open("a",encoding="utf-8",errors="replace") as log:
        log.write("\n=== "+now()+" ===\n"+" ".join(map(str,cmd))+"\n"); log.flush()
        cp=subprocess.run(cmd,cwd=str(cwd),stdout=log,stderr=subprocess.STDOUT,text=True)
    return cp.returncode

def handle(job,repo:Path,hub:str):
    p=json.loads(job["payload_json"])
    if job["kind"]!="gpu_moji_channel":
        raise RuntimeError(f"unsupported GPU job kind: {job['kind']}")
    runner=repo/"scripts"/"run_youtube_channel_harvest.ps1"
    logs=repo/"research"/"runtime"/"logs"
    pairs=[
        ("Url",p["url"]),("Name",p["name"]),
        ("Workers",p.get("caption_workers",8)),
        ("AudioWorkers",p.get("audio_workers",4)),
        ("Device",p.get("device","cuda")),
        ("WhisperModel",p.get("whisper_model","medium.en")),
        ("ComputeType",p.get("compute_type","int8")),
        ("BatchSize",p.get("batch_size",4)),
    ]
    code=run_logged(
        ps(runner,pairs,["ProcessCaptionless","SkipHarvest","SkipAudioDownload"]),
        logs/f"job_{job['id']}_gpu_moji.log",repo
    )
    if code:
        raise RuntimeError(f"Moji GPU pipeline exit code {code}")

    cid=p["channel_id"]; gen=p["generation"]
    enqueue(hub,kind="analysis_sync",lane="cpu",payload=p,job_key=f"analysis:gpu:{cid}:{gen}",priority=30)
    enqueue(hub,kind="spider_channel",lane="cpu",payload=p,job_key=f"spider:gpu:{cid}:{gen}",priority=50)
    return {"exit_code":0,"channel_id":cid,"generation":gen}

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--hub",default="http://127.0.0.1:8765")
    ap.add_argument("--host",default="127.0.0.1")
    ap.add_argument("--port",type=int,default=8767)
    ap.add_argument("--poll",type=float,default=1.0)
    ap.add_argument("--lease-seconds",type=int,default=7200)
    args=ap.parse_args()

    repo=Path(__file__).resolve().parents[1]
    state=State(); StatusAPI.state=state
    server=ThreadingHTTPServer((args.host,args.port),StatusAPI)
    threading.Thread(target=server.serve_forever,daemon=True).start()
    worker=f"{socket.gethostname()}-gpu-1"
    print(f"GPU pipeline service http://{args.host}:{args.port} single-consumer hub={args.hub}")

    try:
        while True:
            try:
                job=lease(args.hub,lane="gpu",worker=worker,kinds=["gpu_moji_channel"],lease_seconds=args.lease_seconds)
            except Exception:
                time.sleep(args.poll); continue
            if not job:
                time.sleep(args.poll); continue
            state.set_active(job); hb=HeartbeatThread(args.hub,job["id"],worker,args.lease_seconds); hb.start(); ok=False
            try:
                result=handle(job,repo,args.hub)
                complete(args.hub,job_id=job["id"],worker=worker,result=result); ok=True
            except Exception as e:
                try: fail(args.hub,job_id=job["id"],worker=worker,error=repr(e),retry_delay=120)
                except Exception: pass
            finally:
                hb.stop(); state.clear(ok)
    except KeyboardInterrupt:
        pass
    finally:
        server.shutdown()
    return 0

if __name__=="__main__":
    raise SystemExit(main())
