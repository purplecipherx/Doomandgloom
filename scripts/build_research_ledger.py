#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path

CAPTION_SUFFIX = ".segments.jsonl"
DIARIZED_NAME = "diarized_transcript.jsonl"
SENTENCE_RE = re.compile(r"(?<=[.!?])\s+(?=(?:[A-Z0-9\"'\(\[]|$))")
SPACE_RE = re.compile(r"\s+")

FIELDS = [
    "unit_id","content_id","source_type","source_path","source_sha256",
    "start_seconds","end_seconds","speaker_id","text","unit_index",
    "source_status","superseded_at","semantic_review_status","fact_check_status","created_at","last_seen_at"
]

def now():
    return datetime.now(timezone.utc).isoformat()

def sha256_file(path: Path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()

def clean(text):
    return SPACE_RE.sub(" ", str(text or "")).strip()

def split_sentences(text):
    text = clean(text)
    if not text:
        return []
    parts = [clean(x) for x in SENTENCE_RE.split(text) if clean(x)]
    return parts or [text]

def stable_id(source_sha, content_id, start, end, speaker, text, index):
    raw = "\x1f".join(map(str, [source_sha, content_id, start, end, speaker, text, index]))
    return "TU_" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24].upper()

def iter_caption(path: Path):
    content_id = path.name[:-len(CAPTION_SUFFIX)]
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            o = json.loads(line)
        except Exception:
            continue
        yield {
            "content_id": content_id,
            "source_type": "youtube_caption",
            "source_path": str(path.resolve()),
            "start_seconds": o.get("start", ""),
            "end_seconds": o.get("end", ""),
            "speaker_id": "",
            "text": o.get("text", ""),
        }

def iter_diarized(path: Path):
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            o = json.loads(line)
        except Exception:
            continue
        yield {
            "content_id": o.get("video_id") or o.get("content_id") or "",
            "source_type": "moji_diarized",
            "source_path": str(path.resolve()),
            "start_seconds": o.get("start_seconds", ""),
            "end_seconds": o.get("end_seconds", ""),
            "speaker_id": o.get("speaker_id", ""),
            "text": o.get("text", ""),
        }

def transcript_files(root: Path):
    for p in root.rglob(f"*{CAPTION_SUFFIX}"):
        yield p, iter_caption
    for p in root.rglob(DIARIZED_NAME):
        yield p, iter_diarized

def load_existing(path: Path):
    if not path.exists():
        return {}
    return {r["unit_id"]: r for r in csv.DictReader(path.open(encoding="utf-8-sig"))}

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--research-root", default="research/youtube")
    ap.add_argument("--output-dir", default="data/analysis")
    args = ap.parse_args()

    research = Path(args.research_root).resolve()
    out = Path(args.output_dir).resolve()
    out.mkdir(parents=True, exist_ok=True)
    ledger_path = out / "transcript_units.csv"
    existing = load_existing(ledger_path)

    observed_at = now()
    units = dict(existing)
    source_count = 0
    raw_segment_count = 0
    new_count = 0
    observed_source_versions = {}
    current_unit_ids = set()

    for path, reader in transcript_files(research):
        source_count += 1
        digest = sha256_file(path)
        resolved_path = str(path.resolve())
        observed_source_versions[resolved_path] = digest
        for seg in reader(path):
            raw_segment_count += 1
            parts = split_sentences(seg["text"])
            if not parts:
                continue
            start = seg["start_seconds"]
            end = seg["end_seconds"]

            for idx, part in enumerate(parts):
                uid = stable_id(
                    digest, seg["content_id"], start, end,
                    seg["speaker_id"], part, idx
                )
                current_unit_ids.add(uid)
                if uid in units:
                    units[uid]["last_seen_at"] = observed_at
                    units[uid]["source_status"] = "CURRENT"
                    units[uid]["superseded_at"] = ""
                    continue
                units[uid] = {
                    "unit_id": uid,
                    "content_id": seg["content_id"],
                    "source_type": seg["source_type"],
                    "source_path": seg["source_path"],
                    "source_sha256": digest,
                    "start_seconds": start,
                    "end_seconds": end,
                    "speaker_id": seg["speaker_id"],
                    "text": part,
                    "unit_index": idx,
                    "source_status": "CURRENT",
                    "superseded_at": "",
                    "semantic_review_status": "PENDING",
                    "fact_check_status": "PENDING",
                    "created_at": observed_at,
                    "last_seen_at": observed_at,
                }
                new_count += 1

    for uid, row in units.items():
        source_path = row.get("source_path", "")
        if source_path not in observed_source_versions:
            continue
        if uid in current_unit_ids:
            continue
        if row.get("source_sha256", "") != observed_source_versions[source_path]:
            row["source_status"] = "SUPERSEDED"
            if not row.get("superseded_at"):
                row["superseded_at"] = observed_at
        else:
            row.setdefault("source_status", "CURRENT")
            row.setdefault("superseded_at", "")

    def time_key(r):
        try:
            return float(r.get("start_seconds") or 0)
        except Exception:
            return 0.0

    rows = sorted(units.values(), key=lambda r: (r.get("content_id",""), time_key(r), r.get("unit_id","")))
    with ledger_path.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)

    qfields = [
        "unit_id","content_id","source_type","source_path","start_seconds",
        "end_seconds","speaker_id","text","semantic_review_status","fact_check_status"
    ]
    pending_path = out / "semantic_review_queue.csv"
    with pending_path.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=qfields)
        w.writeheader()
        for r in rows:
            if r.get("source_status","CURRENT") == "CURRENT" and (
                r.get("semantic_review_status") != "COMPLETE" or r.get("fact_check_status") != "COMPLETE"
            ):
                w.writerow({k:r.get(k,"") for k in qfields})

    manifest = {
        "built_at": observed_at,
        "research_root": str(research),
        "source_files": source_count,
        "raw_transcript_segments": raw_segment_count,
        "unit_count": len(rows),
        "new_unit_count": new_count,
        "current_unit_count": sum(1 for r in rows if r.get("source_status","CURRENT") == "CURRENT"),
        "superseded_unit_count": sum(1 for r in rows if r.get("source_status","CURRENT") == "SUPERSEDED"),
        "pending_review_count": sum(
            1 for r in rows
            if r.get("source_status","CURRENT") == "CURRENT" and (
                r.get("semantic_review_status") != "COMPLETE" or r.get("fact_check_status") != "COMPLETE"
            )
        ),
        "policy": "Every transcript unit is preserved and queued; semantic extraction/fact checking attaches by stable unit_id."
    }
    (out / "transcript_units_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(json.dumps(manifest, indent=2))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
