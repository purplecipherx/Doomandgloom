#!/usr/bin/env python3
from __future__ import annotations

import argparse
import contextlib
import json
import socket
import subprocess
import sys
import threading
import time
from argparse import Namespace
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from pipeline_client import complete, enqueue, fail, heartbeat, lease

def now():
    return datetime.now(timezone.utc).isoformat()

def gpu_memory():
    try:
        import torch
        if not torch.cuda.is_available():
            return {"cuda":False}
        free,total=torch.cuda.mem_get_info()
        return {
            "cuda":True,
            "device":torch.cuda.get_device_name(0),
            "allocated_bytes":int(torch.cuda.memory_allocated()),
            "reserved_bytes":int(torch.cuda.memory_reserved()),
            "free_bytes":int(free),
            "total_bytes":int(total),
        }
    except Exception as e:
        return {"cuda":False,"error":repr(e)}

class State:
    def __init__(self):
        self.lock=threading.Lock(); self.active=None; self.completed=0; self.failed=0; self.started_at=now()
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
            return {
                "service":"gpu","started_at":self.started_at,"active":self.active,
                "completed":self.completed,"failed":self.failed,"gpu_memory":gpu_memory(),"ts":now()
            }

class StatusAPI(BaseHTTPRequestHandler):
    state=None
    def log_message(self,fmt,*args): return
    def do_GET(self):
        if self.path not in ("/health","/status"):
            self.send_response(404); self.end_headers(); return
        obj=self.state.snapshot(); obj["ok"]=True
        data=json.dumps(obj).encode("utf-8")
        try:
            self.send_response(200); self.send_header("Content-Type","application/json")
            self.send_header("Content-Length",str(len(data))); self.end_headers(); self.wfile.write(data)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass

class HeartbeatThread(threading.Thread):
    def __init__(self,hub,job_id,worker,seconds):
        super().__init__(daemon=True); self.hub=hub; self.job_id=job_id; self.worker=worker
        self.seconds=seconds; self.stop_event=threading.Event()
    def run(self):
        interval=max(20,min(90,self.seconds//3))
        while not self.stop_event.wait(interval):
            try: heartbeat(self.hub,job_id=self.job_id,worker=self.worker,lease_seconds=self.seconds)
            except Exception: pass
    def stop(self): self.stop_event.set()

def detect_moji_root(explicit=""):
    if explicit:
        p=Path(explicit).resolve()
        if (p/"voice_harvest.py").exists(): return p
    home=Path.home()
    for p in [
        home/"Desktop"/"M0J1M0J1_VOICE",
        home/"Desktop"/"M0J1M0J1_GPU",
        home/"Desktop"/"M0J1M0J1",
    ]:
        if (p/"voice_harvest.py").exists(): return p
    raise RuntimeError("Could not find M0J1M0J1 voice_harvest.py")

def load_moji(moji_root:Path):
    root=str(moji_root)
    if root not in sys.path: sys.path.insert(0,root)
    from voice_harvester.cli import cmd_scan,cmd_diarize,cmd_embed,cmd_cluster,cmd_extract,cmd_transcribe
    return cmd_scan,cmd_diarize,cmd_embed,cmd_cluster,cmd_extract,cmd_transcribe

def handle(job,repo:Path,hub:str,moji_root:Path,moji_funcs):
    p=json.loads(job["payload_json"])
    if job["kind"] not in {"gpu_moji_channel","gpu_voice_index_channel","gpu_moji_batch"}:
        raise RuntimeError(f"unsupported GPU job kind: {job['kind']}")

    channel_root=repo/"research"/"youtube"/p["name"]
    voice_only = job["kind"]=="gpu_voice_index_channel"
    batch_mode = job["kind"]=="gpu_moji_batch"
    if batch_mode:
        audio_dir=Path(p["audio_batch_dir"])
        audio_manifest=Path(p["audio_manifest_path"])
        moji_out=Path(p["moji_output_path"])
        research_out=Path(p["research_output_path"])
    else:
        audio_dir=channel_root/("voice_audio" if voice_only else "audio_fallback")
        audio_manifest=audio_dir/"audio_manifest.jsonl"
        moji_out=channel_root/("voice_index_work" if voice_only else "moji_work")
        research_out=channel_root/"diarized_transcripts"
    logs=repo/"research"/"runtime"/"logs"
    log_path=logs/f"job_{job['id']}_gpu_moji.log"
    log_path.parent.mkdir(parents=True,exist_ok=True)

    cmd_scan,cmd_diarize,cmd_embed,cmd_cluster,cmd_extract,cmd_transcribe=moji_funcs

    with log_path.open("a",encoding="utf-8",errors="replace") as log, contextlib.redirect_stdout(log), contextlib.redirect_stderr(log):
        print("\n=== "+now()+" ===")
        print(f"Resident Moji root: {moji_root}")
        print(f"GPU memory before: {json.dumps(gpu_memory())}")

        cmd_scan(Namespace(output=str(moji_out),force=False,input=str(audio_dir),hash="sha256"))
        cmd_diarize(Namespace(output=str(moji_out),force=False,hf_token=None,device=p.get("device","cuda")))
        cmd_embed(Namespace(
            output=str(moji_out),force=False,embed_device="cpu",
            embedding_model=p.get("embedding_model","hbredin/wespeaker-voxceleb-resnet34-LM"),
            embedding_segments=int(p.get("embedding_segments",20))
        ))
        cmd_cluster(Namespace(output=str(moji_out),force=False,threshold=float(p.get("cluster_threshold",0.68))))

        if not voice_only:
            cmd_extract(Namespace(
                output=str(moji_out),force=False,sample_rate=int(p.get("sample_rate",44100)),
                gap_ms=int(p.get("gap_ms",350)),min_segment=float(p.get("min_segment",0.8))
            ))
            cmd_transcribe(Namespace(
                output=str(moji_out),force=False,whisper_model=p.get("whisper_model","medium.en"),
                language=p.get("language","en"),device=p.get("device","cuda"),
                compute_type=p.get("compute_type","int8"),batch_size=int(p.get("batch_size",4))
            ))

        print(f"GPU memory after: {json.dumps(gpu_memory())}")

    cid=p["channel_id"]; gen=p["generation"]
    if voice_only:
        next_kind="caption_voice_identity_sync"
        next_key=f"captionvoice:{cid}:{gen}"
    else:
        next_kind="audio_identity_sync"
        batch_suffix=f":{p.get('batch_id')}" if p.get("batch_id") else ""
        next_key=f"voice:{cid}:{gen}{batch_suffix}"
    enqueue(
        hub,kind=next_kind,lane="cpu",payload=p,
        job_key=next_key,priority=15,max_attempts=3
    )
    return {
        "exit_code":0,"channel_id":cid,"generation":gen,
        "moji_output":str(moji_out),
        "next_stage":next_kind,
        "gpu_memory":gpu_memory()
    }

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--hub",default="http://127.0.0.1:8765")
    ap.add_argument("--host",default="127.0.0.1")
    ap.add_argument("--port",type=int,default=8767)
    ap.add_argument("--poll",type=float,default=1.0)
    ap.add_argument("--lease-seconds",type=int,default=7200)
    ap.add_argument("--moji-root",default="")
    args=ap.parse_args()

    repo=Path(__file__).resolve().parents[1]
    moji_root=detect_moji_root(args.moji_root)
    moji_funcs=load_moji(moji_root)

    state=State(); StatusAPI.state=state
    server=ThreadingHTTPServer((args.host,args.port),StatusAPI)
    threading.Thread(target=server.serve_forever,daemon=True).start()
    worker=f"{socket.gethostname()}-gpu-1"
    print(f"GPU pipeline service http://{args.host}:{args.port} single-consumer hub={args.hub}")
    print(f"Resident Moji root: {moji_root}")
    print(json.dumps(gpu_memory(),indent=2))

    try:
        while True:
            try:
                job=lease(args.hub,lane="gpu",worker=worker,kinds=["gpu_moji_channel","gpu_voice_index_channel","gpu_moji_batch"],lease_seconds=args.lease_seconds)
            except Exception:
                time.sleep(args.poll); continue
            if not job:
                time.sleep(args.poll); continue
            state.set_active(job); hb=HeartbeatThread(args.hub,job["id"],worker,args.lease_seconds); hb.start(); ok=False
            try:
                result=handle(job,repo,args.hub,moji_root,moji_funcs)
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
