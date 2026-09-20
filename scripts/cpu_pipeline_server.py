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
VOICE_LOCK = threading.Lock()
HARVEST_SEM = threading.Semaphore(2)
AUDIO_SEM = threading.Semaphore(2)

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
        try:
            self.send_response(200); self.send_header("Content-Type","application/json"); self.send_header("Content-Length",str(len(data))); self.end_headers(); self.wfile.write(data)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass

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

def queue_spider(hub, payload, phase):
    cid=payload["channel_id"]; gen=payload["generation"]
    enqueue(hub,kind="spider_channel",lane="cpu",payload=dict(payload),job_key=f"spider:{phase}:{cid}:{gen}",priority=80)

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
            ("Workers",payload.get("caption_workers",8)),("Sleep",payload.get("sleep",0.75)),
            ("CookiesFromBrowser",payload.get("cookies_from_browser","")),
            ("SleepRequests",payload.get("audio_sleep_requests",1.5)),
            ("SleepInterval",payload.get("audio_sleep_interval",2.0)),
            ("MaxSleepInterval",payload.get("audio_max_sleep_interval",5.0))
        ]
        if int(payload.get("limit_videos",0) or 0)>0: pairs.append(("Limit",payload["limit_videos"]))
        with HARVEST_SEM:
            code=run_logged(ps(runner,pairs),logs/f"job_{job['id']}_harvest.log",repo)
        if code: raise RuntimeError(f"harvest exit code {code}")
        queue_spider(hub,payload,"captions")
        enqueue(hub,kind="prepare_audio",lane="cpu",payload=payload,job_key=f"audio:{payload['channel_id']}:{payload['generation']}",priority=5)
        if not bool(payload.get("force_whisper_all",False)):
            enqueue(hub,kind="prepare_voice_audio",lane="cpu",payload=payload,job_key=f"voiceaudio:{payload['channel_id']}:{payload['generation']}",priority=8)
        return {"exit_code":0,"channel_root":str(channel_root),"force_whisper_all":bool(payload.get("force_whisper_all",False))}

    if kind=="prepare_audio":
        common_audio_args=[]
        cookie_browser=str(payload.get("cookies_from_browser") or "").strip()
        if cookie_browser:
            common_audio_args += ["--cookies-from-browser",cookie_browser]
        common_audio_args += [
            "--sleep-requests",str(payload.get("audio_sleep_requests",1.5)),
            "--sleep-interval",str(payload.get("audio_sleep_interval",2.0)),
            "--max-sleep-interval",str(payload.get("audio_max_sleep_interval",5.0)),
        ]
        force_all=bool(payload.get("force_whisper_all",False))
        queue=channel_root/("inventory.csv" if force_all else "needs_transcription.csv")

        if force_all:
            rows=list(csv.DictReader(queue.open(encoding="utf-8-sig")))
            batch_size=max(1,int(payload.get("audio_batch_size",25) or 25))
            batch_root=channel_root/"full_audio_batches"/payload["generation"]
            batch_root.mkdir(parents=True,exist_ok=True)
            queued=0
            for start in range(0,len(rows),batch_size):
                batch_rows=rows[start:start+batch_size]
                batch_id=f"B{start//batch_size+1:05d}"
                work=batch_root/batch_id
                work.mkdir(parents=True,exist_ok=True)
                batch_queue=work/"queue.csv"
                fields=list(batch_rows[0].keys()) if batch_rows else ["video_id","url","title"]
                with batch_queue.open("w",newline="",encoding="utf-8-sig") as bf:
                    w=csv.DictWriter(bf,fieldnames=fields); w.writeheader(); w.writerows(batch_rows)
                bp=dict(payload)
                bp.update({
                    "batch_id":batch_id,
                    "audio_batch_queue":str(batch_queue),
                    "audio_batch_dir":str(work/"audio"),
                    "audio_manifest_path":str(work/"audio"/"audio_manifest.jsonl"),
                    "moji_output_path":str(work/"moji"),
                    "research_output_path":str(channel_root/"diarized_transcripts"/"batches"/payload["generation"]/batch_id),
                    "defer_analysis":True,
                })
                enqueue(
                    hub,kind="prepare_audio_batch",lane="cpu",payload=bp,
                    job_key=f"audiobatch:{payload['channel_id']}:{payload['generation']}:{batch_id}",
                    priority=8,max_attempts=3
                )
                queued+=1
            return {"exit_code":0,"audio_batches_queued":queued,"batch_size":batch_size,"video_count":len(rows)}

        script=repo/"scripts"/"download_captionless_audio.py"
        cmd=[str(ytpy),str(script),str(queue),"--workers",str(payload.get("audio_workers",audio_workers)),*common_audio_args]
        if int(payload.get("captionless_limit",0) or 0)>0:
            cmd += ["--limit",str(payload["captionless_limit"])]
        with AUDIO_SEM:
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

    if kind=="prepare_audio_batch":
        common_audio_args=[]
        cookie_browser=str(payload.get("cookies_from_browser") or "").strip()
        if cookie_browser:
            common_audio_args += ["--cookies-from-browser",cookie_browser]
        common_audio_args += [
            "--sleep-requests",str(payload.get("audio_sleep_requests",1.5)),
            "--sleep-interval",str(payload.get("audio_sleep_interval",2.0)),
            "--max-sleep-interval",str(payload.get("audio_max_sleep_interval",5.0)),
        ]
        queue=Path(payload["audio_batch_queue"])
        output_dir=Path(payload["audio_batch_dir"])
        script=repo/"scripts"/"download_captionless_audio.py"
        cmd=[
            str(ytpy),str(script),str(queue),
            "--output-dir",str(output_dir),
            "--workers",str(payload.get("audio_workers",audio_workers)),
            *common_audio_args
        ]
        with AUDIO_SEM:
            code=run_logged(cmd,logs/f"job_{job['id']}_audio_batch.log",repo)
        if code:
            raise RuntimeError(f"audio batch prefetch exit code {code}")
        manifest=Path(payload["audio_manifest_path"])
        ready=0
        if manifest.exists():
            for line in manifest.read_text(encoding="utf-8",errors="replace").splitlines():
                try:
                    r=json.loads(line)
                    if r.get("status") in ("downloaded","cached") and r.get("audio_path"):
                        ready+=1
                except Exception:
                    pass
        if ready:
            enqueue(
                hub,kind="gpu_moji_batch",lane="gpu",payload=payload,
                job_key=f"gpubatch:{payload['channel_id']}:{payload['generation']}:{payload['batch_id']}",
                priority=20,max_attempts=2
            )
        return {"exit_code":0,"batch_id":payload["batch_id"],"audio_ready":ready}

    if kind=="prepare_voice_audio":
        caption_status=channel_root/"caption_status.csv"
        queue_script=repo/"scripts"/"build_voice_index_queue.py"
        voice_queue=channel_root/"voice_index_queue.csv"
        code=run_logged([
            str(ytpy),str(queue_script),str(caption_status),"--output",str(voice_queue)
        ],logs/f"job_{job['id']}_voice_queue.log",repo)
        if code:
            raise RuntimeError(f"voice index queue build exit code {code}")

        rows=list(csv.DictReader(voice_queue.open(encoding="utf-8-sig"))) if voice_queue.exists() else []
        if int(payload.get("voice_index_limit",0) or 0)>0:
            rows=rows[:int(payload["voice_index_limit"])]
        batch_size=max(1,int(payload.get("sparse_voice_batch_size",10) or 10))
        batch_root=channel_root/"sparse_voice_batches"/payload["generation"]
        batch_root.mkdir(parents=True,exist_ok=True)
        queued=0
        for start_idx in range(0,len(rows),batch_size):
            batch_rows=rows[start_idx:start_idx+batch_size]
            batch_id=f"VB{start_idx//batch_size+1:05d}"
            work=batch_root/batch_id
            work.mkdir(parents=True,exist_ok=True)
            batch_queue=work/"queue.csv"
            fields=list(batch_rows[0].keys()) if batch_rows else ["video_id","url","title","channel_name","reason"]
            with batch_queue.open("w",newline="",encoding="utf-8-sig") as bf:
                w=csv.DictWriter(bf,fieldnames=fields); w.writeheader(); w.writerows(batch_rows)
            bp=dict(payload)
            bp.update({
                "batch_id":batch_id,
                "sparse_voice_batch_queue":str(batch_queue),
                "audio_batch_dir":str(work/"audio"),
                "audio_manifest_path":str(work/"audio"/"audio_manifest.jsonl"),
                "sparse_sample_root":str(work/"samples"),
                "sparse_sample_dir":str(work/"samples"/"clips"),
                "sample_manifest_path":str(work/"samples"/"sample_manifest.jsonl"),
                "moji_output_path":str(work/"moji"),
                "research_output_path":str(work/"attribution"),
                "sparse_voice_batch_root":str(batch_root),
                "sparse_voice_total_batches":(len(rows)+batch_size-1)//batch_size if rows else 0,
                "defer_analysis":True,
            })
            enqueue(
                hub,kind="prepare_sparse_voice_batch",lane="cpu",payload=bp,
                job_key=f"sparseaudio:{payload['channel_id']}:{payload['generation']}:{batch_id}",
                priority=9,max_attempts=3
            )
            queued+=1
        if not rows:
            enqueue(hub,kind="analysis_sync",lane="cpu",payload=payload,
                    job_key=f"analysis:nocaptionvoice:{payload['channel_id']}:{payload['generation']}",priority=30)
        return {"exit_code":0,"sparse_voice_batches_queued":queued,"batch_size":batch_size,"video_count":len(rows)}

    if kind=="prepare_sparse_voice_batch":
        common_audio_args=[]
        cookie_browser=str(payload.get("cookies_from_browser") or "").strip()
        if cookie_browser:
            common_audio_args += ["--cookies-from-browser",cookie_browser]
        common_audio_args += [
            "--sleep-requests",str(payload.get("audio_sleep_requests",1.5)),
            "--sleep-interval",str(payload.get("audio_sleep_interval",2.0)),
            "--max-sleep-interval",str(payload.get("audio_max_sleep_interval",5.0)),
        ]
        queue=Path(payload["sparse_voice_batch_queue"])
        output_dir=Path(payload["audio_batch_dir"])
        downloader=repo/"scripts"/"download_captionless_audio.py"
        cmd=[str(ytpy),str(downloader),str(queue),"--output-dir",str(output_dir),
             "--workers",str(payload.get("audio_workers",audio_workers)),*common_audio_args]
        with AUDIO_SEM:
            code=run_logged(cmd,logs/f"job_{job['id']}_sparse_audio.log",repo)
        if code:
            raise RuntimeError(f"sparse voice audio acquisition exit code {code}")

        sample_root=Path(payload["sparse_sample_root"])
        sampler=repo/"scripts"/"build_sparse_voice_samples.py"
        code=run_logged([
            str(ytpy),str(sampler),
            "--normalized-dir",str(channel_root/"normalized"),
            "--audio-manifest",str(payload["audio_manifest_path"]),
            "--output",str(sample_root),
            "--interval-seconds",str(payload.get("sparse_voice_interval_seconds",90)),
            "--clip-seconds",str(payload.get("sparse_voice_clip_seconds",3.0)),
            "--min-cue-seconds",str(payload.get("sparse_voice_min_cue_seconds",1.8)),
            "--min-words",str(payload.get("sparse_voice_min_words",3)),
            "--max-samples-per-video",str(payload.get("sparse_voice_max_samples_per_video",80)),
        ],logs/f"job_{job['id']}_sparse_samples.log",repo)
        if code:
            raise RuntimeError(f"sparse voice sample extraction exit code {code}")

        summary_path=sample_root/"sample_summary.json"
        sample_count=0
        if summary_path.exists():
            try: sample_count=int(json.loads(summary_path.read_text(encoding="utf-8")).get("sample_count") or 0)
            except Exception: pass
        if sample_count:
            enqueue(
                hub,kind="gpu_sparse_voice_batch",lane="gpu",payload=payload,
                job_key=f"gpusparse:{payload['channel_id']}:{payload['generation']}:{payload['batch_id']}",
                priority=18,max_attempts=2
            )
        else:
            done=Path(payload["research_output_path"])/"identity_done.json"
            done.parent.mkdir(parents=True,exist_ok=True)
            done.write_text(json.dumps({"status":"no_samples","batch_id":payload["batch_id"]}),encoding="utf-8")
        return {"exit_code":0,"batch_id":payload["batch_id"],"sample_count":sample_count}

    if kind=="sparse_voice_identity_sync":
        identity_script=repo/"scripts"/"audio_identity_db.py"
        audio_manifest=Path(payload["audio_manifest_path"])
        moji_out=Path(payload["moji_output_path"])
        resolution=repo/"data"/"audio"/"speaker_resolution_current.csv"
        matches=repo/"data"/"audio"/"voice_match_candidates.csv"
        hypotheses=repo/"data"/"audio"/"identity_hypotheses.csv"
        attribution_out=Path(payload["research_output_path"])
        voice_log=logs/f"job_{job['id']}_sparse_voice_identity.log"

        with VOICE_LOCK:
            commands=[
                [str(ytpy),str(identity_script),"ingest-audio","--manifest",str(audio_manifest),"--channel-id",payload["channel_id"]],
                [str(ytpy),str(identity_script),"ingest-moji","--moji-output",str(moji_out),"--channel-id",payload["channel_id"]],
                [str(ytpy),str(identity_script),"extract-exemplars","--moji-output",str(moji_out)],
                [str(ytpy),str(identity_script),"match","--min-similarity",str(payload.get("voice_match_floor",0.58))],
                [str(ytpy),str(identity_script),"export","--output",str(resolution)],
                [str(ytpy),str(identity_script),"export-matches","--output",str(matches)],
                [str(ytpy),str(identity_script),"export-hypotheses","--output",str(hypotheses)],
            ]
            for cmd in commands:
                code=run_logged(cmd,voice_log,repo)
                if code:
                    raise RuntimeError(f"sparse voice identity stage failed exit={code}: {' '.join(cmd)}")

            align=repo/"scripts"/"align_sparse_captions_to_speakers.py"
            code=run_logged([
                str(ytpy),str(align),
                "--moji-output",str(moji_out),
                "--sample-manifest",str(payload["sample_manifest_path"]),
                "--normalized-dir",str(channel_root/"normalized"),
                "--speaker-resolution",str(resolution),
                "--channel-id",payload["channel_id"],
                "--output",str(attribution_out),
            ],voice_log,repo)
            if code:
                raise RuntimeError(f"sparse caption speaker alignment exit code {code}")

        done=attribution_out/"identity_done.json"
        done.write_text(json.dumps({"status":"done","batch_id":payload["batch_id"],"ts":now()}),encoding="utf-8")

        batch_root=Path(payload["sparse_voice_batch_root"])
        total=int(payload.get("sparse_voice_total_batches",0) or 0)
        completed=len(list(batch_root.glob("VB*/attribution/identity_done.json")))
        if total and completed>=total:
            finalizer=repo/"scripts"/"finalize_sparse_voice_channel.py"
            final_out=channel_root/"speaker_attribution"
            code=run_logged([
                str(ytpy),str(finalizer),"--batch-root",str(batch_root),"--output",str(final_out)
            ],logs/f"job_{job['id']}_sparse_finalize.log",repo)
            if code:
                raise RuntimeError(f"sparse channel finalization exit code {code}")
            cid=payload["channel_id"]; gen=payload["generation"]
            enqueue(hub,kind="analysis_sync",lane="cpu",payload=payload,
                    job_key=f"analysis:sparsevoice:{cid}:{gen}",priority=30)
        return {"exit_code":0,"batch_id":payload["batch_id"],"completed_batches":completed,"total_batches":total}

    if kind=="caption_voice_identity_sync":
        identity_script=repo/"scripts"/"audio_identity_db.py"
        audio_manifest=channel_root/"voice_audio"/"audio_manifest.jsonl"
        moji_out=channel_root/"voice_index_work"
        resolution=repo/"data"/"audio"/"speaker_resolution_current.csv"
        matches=repo/"data"/"audio"/"voice_match_candidates.csv"
        hypotheses=repo/"data"/"audio"/"identity_hypotheses.csv"
        attribution_out=channel_root/"speaker_attribution"
        voice_log=logs/f"job_{job['id']}_caption_voice_identity.log"

        with VOICE_LOCK:
            commands=[
                [str(ytpy),str(identity_script),"ingest-audio","--manifest",str(audio_manifest),"--channel-id",payload["channel_id"]],
                [str(ytpy),str(identity_script),"ingest-moji","--moji-output",str(moji_out),"--channel-id",payload["channel_id"]],
                [str(ytpy),str(identity_script),"extract-exemplars","--moji-output",str(moji_out)],
                [str(ytpy),str(identity_script),"match","--min-similarity",str(payload.get("voice_match_floor",0.58))],
                [str(ytpy),str(identity_script),"export","--output",str(resolution)],
                [str(ytpy),str(identity_script),"export-matches","--output",str(matches)],
                [str(ytpy),str(identity_script),"export-hypotheses","--output",str(hypotheses)],
            ]
            for cmd in commands:
                code=run_logged(cmd,voice_log,repo)
                if code:
                    raise RuntimeError(f"caption voice identity stage failed exit={code}: {' '.join(cmd)}")

            align=repo/"scripts"/"align_captions_to_speakers.py"
            code=run_logged([
                str(ytpy),str(align),
                "--moji-output",str(moji_out),
                "--normalized-dir",str(channel_root/"normalized"),
                "--audio-manifest",str(audio_manifest),
                "--speaker-resolution",str(resolution),
                "--channel-id",payload["channel_id"],
                "--output",str(attribution_out),
            ],voice_log,repo)
            if code:
                raise RuntimeError(f"caption speaker alignment exit code {code}")

        cid=payload["channel_id"]; gen=payload["generation"]
        enqueue(hub,kind="analysis_sync",lane="cpu",payload=payload,
                job_key=f"analysis:captionvoice:{cid}:{gen}",priority=30)
        return {
            "exit_code":0,
            "speaker_resolution":str(resolution),
            "caption_attribution":str(attribution_out/"caption_speaker_attribution.csv"),
        }

    if kind=="audio_identity_sync":
        identity_script=repo/"scripts"/"audio_identity_db.py"
        audio_manifest=Path(payload.get("audio_manifest_path") or (channel_root/"audio_fallback"/"audio_manifest.jsonl"))
        moji_out=Path(payload.get("moji_output_path") or (channel_root/"moji_work"))
        research_out=Path(payload.get("research_output_path") or (channel_root/"diarized_transcripts"))
        resolution=repo/"data"/"audio"/"speaker_resolution_current.csv"
        voice_log=logs/f"job_{job['id']}_voice_identity.log"

        with VOICE_LOCK:
            commands=[
                [str(ytpy),str(identity_script),"ingest-audio","--manifest",str(audio_manifest),"--channel-id",payload["channel_id"]],
                [str(ytpy),str(identity_script),"ingest-moji","--moji-output",str(moji_out),"--channel-id",payload["channel_id"]],
                [str(ytpy),str(identity_script),"extract-exemplars","--moji-output",str(moji_out)],
                [str(ytpy),str(identity_script),"match","--min-similarity",str(payload.get("voice_match_floor",0.58))],
                [str(ytpy),str(identity_script),"export","--output",str(resolution)],
            ]
            for cmd in commands:
                code=run_logged(cmd,voice_log,repo)
                if code:
                    raise RuntimeError(f"voice identity stage failed exit={code}: {' '.join(cmd)}")

            bridge=repo/"scripts"/"import_moji_research_transcripts.py"
            bridge_cmd=[
                str(ytpy),str(bridge),
                "--moji-output",str(moji_out),
                "--audio-manifest",str(audio_manifest),
                "--output",str(research_out),
                "--speaker-resolution",str(resolution),
                "--channel-id",payload["channel_id"],
            ]
            code=run_logged(bridge_cmd,voice_log,repo)
            if code:
                raise RuntimeError(f"voice-aware timestamp bridge exit code {code}")

        cid=payload["channel_id"]; gen=payload["generation"]
        if not bool(payload.get("defer_analysis",False)):
            enqueue(hub,kind="analysis_sync",lane="cpu",payload=payload,job_key=f"analysis:voice:{cid}:{gen}",priority=30)
            enqueue(hub,kind="spider_channel",lane="cpu",payload=payload,job_key=f"spider:voice:{cid}:{gen}",priority=50)
        return {
            "exit_code":0,
            "speaker_resolution":str(resolution),
            "diarized_transcript":str(research_out/"diarized_transcript.csv"),
        }

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
    # Only one worker leases bulk audio batches. AUDIO_SEM still protects the
    # actual downloader, while the remaining CPU workers stay available for
    # harvest fan-out, spidering, identity sync, and analysis instead of
    # blocking behind the audio semaphore.
    if index == 1:
        kinds=["harvest_channel","prepare_audio","prepare_audio_batch","prepare_voice_audio","prepare_sparse_voice_batch","caption_voice_identity_sync","sparse_voice_identity_sync","audio_identity_sync","analysis_sync","spider_channel"]
    else:
        kinds=["harvest_channel","prepare_audio","prepare_voice_audio","caption_voice_identity_sync","sparse_voice_identity_sync","audio_identity_sync","analysis_sync","spider_channel"]
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
    ap.add_argument("--harvest-slots",type=int,default=2)
    ap.add_argument("--audio-slots",type=int,default=2)
    ap.add_argument("--poll",type=float,default=1.0)
    ap.add_argument("--lease-seconds",type=int,default=1800)
    args=ap.parse_args()
    global HARVEST_SEM, AUDIO_SEM
    HARVEST_SEM = threading.Semaphore(max(1,args.harvest_slots))
    AUDIO_SEM = threading.Semaphore(max(1,args.audio_slots))
    repo=Path(__file__).resolve().parents[1]
    state=State(); StatusAPI.state=state
    server=ThreadingHTTPServer((args.host,args.port),StatusAPI)
    threading.Thread(target=server.serve_forever,daemon=True).start()
    print(f"CPU pipeline service http://{args.host}:{args.port} workers={args.workers} harvest_slots={args.harvest_slots} audio_slots={args.audio_slots} hub={args.hub}")
    with ThreadPoolExecutor(max_workers=max(1,args.workers)) as ex:
        for i in range(max(1,args.workers)): ex.submit(worker_loop,i+1,args,repo,state)
        try:
            while True: time.sleep(3600)
        except KeyboardInterrupt: pass
    server.shutdown(); return 0

if __name__=="__main__":
    raise SystemExit(main())
