#!/usr/bin/env python3
"""
Producer/consumer YouTube research pipeline.

Network-bound acquisition runs across multiple channels concurrently.
Completed channel queues are consumed serially by the GPU/M0J1M0J1 stage while
remaining channels continue harvesting in the background.

This intentionally keeps exactly one GPU consumer on machines with limited VRAM.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path


def now():
    return datetime.now(timezone.utc).isoformat()


def safe_name(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]", "_", value or "youtube_source")


def ps_cmd(script: Path, pairs: list[tuple[str, str | None]], switches: list[str] | None = None):
    cmd = ["powershell.exe", "-ExecutionPolicy", "Bypass", "-File", str(script)]
    for key, value in pairs:
        if value is None:
            continue
        cmd.extend([f"-{key}", str(value)])
    for sw in switches or []:
        cmd.append(f"-{sw}")
    return cmd


def run_logged(cmd: list[str], log_path: Path):
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("w", encoding="utf-8", errors="replace") as log:
        cp = subprocess.run(cmd, stdout=log, stderr=subprocess.STDOUT, text=True)
    return cp.returncode


def run_visible(cmd: list[str]):
    return subprocess.run(cmd).returncode


def main():
    ap = argparse.ArgumentParser(description="Overlap multi-channel YouTube acquisition with one serial GPU/Moji consumer.")
    ap.add_argument("--registry", default="data/youtube_channels.csv")
    ap.add_argument("--channel-workers", type=int, default=2)
    ap.add_argument("--workers", type=int, default=8, help="caption/metadata workers inside each active channel")
    ap.add_argument("--audio-workers", type=int, default=4)
    ap.add_argument("--limit-channels", type=int, default=0)
    ap.add_argument("--limit-videos", type=int, default=0)
    ap.add_argument("--captionless-limit", type=int, default=0)
    ap.add_argument("--sleep", type=float, default=0.75)
    ap.add_argument("--device", choices=["cuda", "cpu"], default="cuda")
    ap.add_argument("--whisper-model", default="medium.en")
    ap.add_argument("--compute-type", default="int8")
    ap.add_argument("--batch-size", type=int, default=4)
    ap.add_argument("--skip-spider", action="store_true")
    args = ap.parse_args()

    repo = Path(__file__).resolve().parents[1]
    registry = (repo / args.registry).resolve()
    runner = repo / "scripts" / "run_youtube_channel_harvest.ps1"
    spider = repo / "scripts" / "run_transcript_spider.ps1"
    research = repo / "research" / "youtube"

    rows = list(csv.DictReader(registry.open(encoding="utf-8-sig")))
    channels = [
        r for r in rows
        if (r.get("enabled") or "").strip().lower() == "true"
        and (r.get("verification_status") or "").strip().lower() == "verified"
    ]
    if args.limit_channels > 0:
        channels = channels[:args.limit_channels]

    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "_pipeline"
    run_dir = research / "pipeline_runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    manifest = {
        "run_id": run_id,
        "started_at": now(),
        "registry": str(registry),
        "channel_count": len(channels),
        "channel_workers": args.channel_workers,
        "caption_workers_per_channel": args.workers,
        "audio_workers": args.audio_workers,
        "gpu_consumers": 1,
        "limit_videos": args.limit_videos,
        "captionless_limit": args.captionless_limit,
        "device": args.device,
        "whisper_model": args.whisper_model,
        "compute_type": args.compute_type,
        "batch_size": args.batch_size,
    }
    (run_dir / "pipeline_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    print()
    print("=== DOOMANDGLOOM PRODUCER/CONSUMER PIPELINE ===")
    print(f"Channels:          {len(channels)}")
    print(f"Channel producers: {max(1, args.channel_workers)}")
    print(f"Caption workers:   {max(1, args.workers)} per active producer")
    print(f"Audio workers:     {max(1, args.audio_workers)}")
    print("GPU consumers:     1")
    print(f"Audit:             {run_dir}")
    print()

    results = []

    def acquire(ch):
        cid = (ch.get("channel_id") or "").strip()
        name = safe_name(cid)
        print(f"[producer:start] {cid} {ch.get('channel_name','')}", flush=True)
        pairs = [
            ("Url", ch.get("youtube_url", "")),
            ("Name", name),
            ("Workers", str(max(1, args.workers))),
            ("Sleep", str(args.sleep)),
        ]
        if args.limit_videos > 0:
            pairs.append(("Limit", str(args.limit_videos)))
        cmd = ps_cmd(runner, pairs)
        code = run_logged(cmd, run_dir / f"acquire_{name}.log")
        print(f"[producer:done]  {cid} exit={code}", flush=True)
        return ch, code

    channel_workers = max(1, min(args.channel_workers, max(1, len(channels))))
    with ThreadPoolExecutor(max_workers=channel_workers) as ex:
        futures = [ex.submit(acquire, ch) for ch in channels]

        # The main thread is the one-and-only GPU consumer.
        for fut in as_completed(futures):
            ch, acquire_code = fut.result()
            cid = (ch.get("channel_id") or "").strip()
            name = safe_name(cid)
            rec = {
                "channel_id": cid,
                "entity_id": ch.get("entity_id", ""),
                "channel_name": ch.get("channel_name", ""),
                "youtube_url": ch.get("youtube_url", ""),
                "acquire_exit_code": acquire_code,
                "gpu_exit_code": "",
                "spider_exit_code": "",
                "completed_at": "",
            }

            if acquire_code != 0:
                print(f"[consumer:skip] {cid}: acquisition failed; see acquire_{name}.log", flush=True)
                rec["completed_at"] = now()
                results.append(rec)
                continue

            print(f"\n[consumer:start] {cid} -> audio/Moji/GPU", flush=True)
            pairs = [
                ("Url", ch.get("youtube_url", "")),
                ("Name", name),
                ("Workers", str(max(1, args.workers))),
                ("AudioWorkers", str(max(1, args.audio_workers))),
                ("Device", args.device),
                ("WhisperModel", args.whisper_model),
                ("ComputeType", args.compute_type),
                ("BatchSize", str(args.batch_size)),
            ]
            if args.captionless_limit > 0:
                pairs.append(("CaptionlessLimit", str(args.captionless_limit)))
            gpu_cmd = ps_cmd(runner, pairs, ["ProcessCaptionless", "SkipHarvest"])
            gpu_code = run_visible(gpu_cmd)
            rec["gpu_exit_code"] = gpu_code

            if gpu_code == 0 and not args.skip_spider:
                batch_id = f"{run_id}_{cid}"
                channel_root = research / name
                spider_cmd = ps_cmd(
                    spider,
                    [
                        ("ResearchRoot", str(channel_root)),
                        ("BatchId", batch_id),
                        ("SourceLabel", cid),
                    ],
                )
                print(f"[spider:start] {cid}", flush=True)
                spider_code = run_visible(spider_cmd)
                rec["spider_exit_code"] = spider_code
            elif args.skip_spider:
                rec["spider_exit_code"] = "skipped"

            rec["completed_at"] = now()
            results.append(rec)
            print(f"[consumer:done] {cid} gpu={gpu_code} spider={rec['spider_exit_code']}", flush=True)

    fields = [
        "channel_id","entity_id","channel_name","youtube_url",
        "acquire_exit_code","gpu_exit_code","spider_exit_code","completed_at"
    ]
    with (run_dir / "pipeline_results.csv").open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(results)

    manifest["completed_at"] = now()
    manifest["results"] = results
    manifest["failed_acquisition_count"] = sum(1 for r in results if r["acquire_exit_code"] != 0)
    manifest["failed_gpu_count"] = sum(
        1 for r in results
        if r["acquire_exit_code"] == 0 and r["gpu_exit_code"] not in (0, "0")
    )
    (run_dir / "pipeline_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    print()
    print("=== PIPELINE COMPLETE ===")
    print(run_dir / "pipeline_results.csv")
    return 1 if manifest["failed_acquisition_count"] or manifest["failed_gpu_count"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
