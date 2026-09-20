#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


def now():
    return datetime.now(timezone.utc).isoformat()


def main():
    ap = argparse.ArgumentParser(description="Rebuild spider index while preserving superseded audit runs.")
    ap.add_argument("--research-root", default="research/youtube")
    ap.add_argument("--output-dir", default="data/spider")
    ap.add_argument("--batch-id", default="")
    ap.add_argument("--source-label", default="rebuild_all")
    ap.add_argument("--reason", default="extractor_rules_rebuild")
    args = ap.parse_args()

    repo = Path(__file__).resolve().parents[1]
    research = (repo / args.research_root).resolve()
    out = (repo / args.output_dir).resolve()
    runs = out / "runs"
    archive = out / "archive"
    archive.mkdir(parents=True, exist_ok=True)

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    batch_id = args.batch_id or f"{stamp}_REBUILD"

    superseded = []
    if runs.exists():
        for manifest_path in sorted(runs.glob("*/spider_manifest.json")):
            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            except Exception:
                continue
            if manifest.get("superseded"):
                continue
            manifest["superseded"] = True
            manifest["superseded_at"] = now()
            manifest["superseded_reason"] = args.reason
            manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
            superseded.append(manifest.get("batch_id") or manifest_path.parent.name)

    processed = out / "processed_transcripts.csv"
    processed_backup = None
    if processed.exists():
        processed_backup = archive / f"processed_transcripts_{stamp}.csv"
        shutil.copy2(processed, processed_backup)
        processed.unlink()

    rebuild_manifest = {
        "rebuild_id": batch_id,
        "started_at": now(),
        "research_root": str(research),
        "output_dir": str(out),
        "superseded_batches": superseded,
        "processed_ledger_backup": str(processed_backup) if processed_backup else "",
        "reason": args.reason,
    }
    rebuild_manifest_path = archive / f"rebuild_{stamp}.json"
    rebuild_manifest_path.write_text(json.dumps(rebuild_manifest, indent=2), encoding="utf-8")

    spider = repo / "scripts" / "transcript_spider.py"
    cmd = [
        sys.executable, str(spider),
        "--research-root", str(research),
        "--output-dir", str(out),
        "--batch-id", batch_id,
        "--source-label", args.source_label,
    ]
    print(f"Superseded {len(superseded)} prior active spider run(s).")
    print(f"Rebuilding from: {research}")
    print(f"New batch: {batch_id}")
    cp = subprocess.run(cmd)

    rebuild_manifest["completed_at"] = now()
    rebuild_manifest["exit_code"] = cp.returncode
    rebuild_manifest["status"] = "complete" if cp.returncode == 0 else "failed"
    rebuild_manifest_path.write_text(json.dumps(rebuild_manifest, indent=2), encoding="utf-8")

    if cp.returncode != 0 and processed_backup and processed_backup.exists() and not processed.exists():
        shutil.copy2(processed_backup, processed)
        print("Rebuild failed; restored previous processed_transcripts.csv.")
    return cp.returncode


if __name__ == "__main__":
    raise SystemExit(main())
