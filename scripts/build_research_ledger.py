#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
from difflib import SequenceMatcher
from datetime import datetime, timezone
from pathlib import Path

CAPTION_SUFFIX = ".segments.jsonl"
DIARIZED_NAME = "diarized_transcript.jsonl"
SENTENCE_RE = re.compile(r"(?<=[.!?])\s+(?=(?:[A-Z0-9\"'\(\[]|$))")
SPACE_RE = re.compile(r"\s+")
BUILDER_VERSION = "caption_overlap_v2"

FIELDS = [
    "unit_id","content_id","source_type","source_path","source_sha256",
    "channel_id","platform_channel_id","channel_name","title","canonical_url",
    "published_at","published_date","publication_precision",
    "start_seconds","end_seconds","speaker_id","raw_speaker_id","acoustic_cluster_id",
    "canonical_voice_id","resolved_entity_id","speaker_resolution_status",
    "speaker_resolution_confidence","speaker_display_name","text","unit_index","builder_version",
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

def stable_id(source_sha, content_id, start, end, speaker, text, index, builder_version=BUILDER_VERSION):
    raw = "\x1f".join(map(str, [source_sha, content_id, start, end, speaker, text, index, builder_version]))
    return "TU_" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24].upper()

def _caption_token_norm(token):
    raw = str(token or "").lower().replace("’", "'")
    cleaned = re.sub(r"[^a-z0-9@_'-]+", "", raw)
    return cleaned or raw.strip()

def _caption_overlap(existing_norm, incoming_norm, max_window=96):
    limit = min(len(existing_norm), len(incoming_norm), max_window)
    for k in range(limit, 0, -1):
        if existing_norm[-k:] == incoming_norm[:k]:
            return k
    # Auto-caption revisions can change one token/punctuation while retaining the
    # same rolling window. Allow only high-similarity fuzzy overlaps of >=4 tokens.
    for k in range(limit, 3, -1):
        ratio = SequenceMatcher(None, existing_norm[-k:], incoming_norm[:k], autojunk=False).ratio()
        if ratio >= 0.92:
            return k
    return 0

def reconstruct_caption_segments(path: Path, max_words=42, gap_seconds=1.75):
    cues=[]
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            o=json.loads(line)
            st=float(o.get("start") or 0)
            en=float(o.get("end") or st)
            text=clean(o.get("text",""))
        except Exception:
            continue
        if text:
            cues.append((st,en,text))

    stream=[]
    norms=[]
    raw_cue_count=len(cues)
    for st,en,text in cues:
        tokens=text.split()
        if not tokens:
            continue
        incoming=[_caption_token_norm(t) for t in tokens]
        k=_caption_overlap(norms,incoming)
        duration=max(0.001,en-st)
        n=len(tokens)
        for j,token in enumerate(tokens[k:],start=k):
            ts=st+duration*(j/n)
            te=st+duration*((j+1)/n)
            stream.append({"token":token,"start":ts,"end":te})
            norms.append(incoming[j])

    segments=[]
    current=[]
    def flush():
        nonlocal current
        if not current:
            return
        text=clean(" ".join(x["token"] for x in current))
        if text:
            segments.append({
                "start_seconds":current[0]["start"],
                "end_seconds":current[-1]["end"],
                "text":text,
            })
        current=[]

    for i,tok in enumerate(stream):
        if current and tok["start"]-current[-1]["end"] > gap_seconds:
            flush()
        current.append(tok)
        token_text=tok["token"].strip()
        sentence_end=bool(re.search(r"[.!?][\"')\]]*$", token_text))
        next_gap=0.0
        if i+1 < len(stream):
            next_gap=max(0.0,stream[i+1]["start"]-tok["end"])
        if sentence_end or len(current)>=max_words or next_gap>gap_seconds:
            flush()
    flush()

    return segments, {
        "raw_cues":raw_cue_count,
        "reconstructed_tokens":len(stream),
        "reconstructed_segments":len(segments),
    }

_META_CACHE = {}

def _channel_root(path: Path):
    for p in [path.parent, *path.parents]:
        if re.fullmatch(r"YT\d+", p.name, re.I):
            return p
    return None

def _iso_from_metadata(meta):
    for key in ("release_timestamp","timestamp"):
        value=meta.get(key)
        if value not in (None,""):
            try:
                dt=datetime.fromtimestamp(float(value),tz=timezone.utc)
                return dt.isoformat(),dt.date().isoformat(),"TIMESTAMP"
            except Exception:
                pass
    raw=str(meta.get("upload_date") or meta.get("release_date") or "").strip()
    if re.fullmatch(r"\d{8}",raw):
        return f"{raw[:4]}-{raw[4:6]}-{raw[6:8]}T00:00:00+00:00",f"{raw[:4]}-{raw[4:6]}-{raw[6:8]}","DATE"
    return "","","UNKNOWN"

def load_media_metadata(path: Path, content_id: str):
    root=_channel_root(path)
    channel_id=root.name if root else ""
    cache_key=(str(root) if root else "",content_id)
    if cache_key in _META_CACHE:
        return dict(_META_CACHE[cache_key])
    meta={}
    if root:
        mp=root/"metadata"/f"{content_id}.json"
        if mp.exists():
            try: meta=json.loads(mp.read_text(encoding="utf-8",errors="replace"))
            except Exception: meta={}
        if not meta:
            inv=root/"inventory.csv"
            if inv.exists():
                try:
                    for r in csv.DictReader(inv.open(encoding="utf-8-sig")):
                        if (r.get("video_id") or r.get("id") or "")==content_id:
                            meta=dict(r);break
                except Exception:
                    pass
    published_at,published_date,precision=_iso_from_metadata(meta)
    result={
        "channel_id":channel_id,
        "platform_channel_id":str(meta.get("channel_id") or meta.get("uploader_id") or ""),
        "channel_name":str(meta.get("channel") or meta.get("uploader") or meta.get("channel_name") or ""),
        "title":str(meta.get("title") or ""),
        "canonical_url":str(meta.get("webpage_url") or meta.get("original_url") or meta.get("url") or (f"https://www.youtube.com/watch?v={content_id}" if content_id else "")),
        "published_at":published_at,
        "published_date":published_date,
        "publication_precision":precision,
    }
    _META_CACHE[cache_key]=dict(result)
    return result

def iter_caption(path: Path):
    content_id = path.name[:-len(CAPTION_SUFFIX)]
    metadata=load_media_metadata(path,content_id)
    segments,_stats=reconstruct_caption_segments(path)
    for o in segments:
        yield {
            "content_id": content_id,
            "source_type": "youtube_caption",
            **metadata,
            "source_path": str(path.resolve()),
            "start_seconds": o.get("start_seconds", ""),
            "end_seconds": o.get("end_seconds", ""),
            "speaker_id": "",
            "builder_version": BUILDER_VERSION,
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
        content_id=o.get("video_id") or o.get("content_id") or ""
        metadata=load_media_metadata(path,content_id)
        yield {
            "content_id": content_id,
            "source_type": "moji_diarized",
            **metadata,
            "source_path": str(path.resolve()),
            "start_seconds": o.get("start_seconds", ""),
            "end_seconds": o.get("end_seconds", ""),
            "speaker_id": o.get("speaker_id", ""),
            "raw_speaker_id": o.get("raw_speaker_id", o.get("speaker_id", "")),
            "acoustic_cluster_id": o.get("acoustic_cluster_id", ""),
            "canonical_voice_id": o.get("canonical_voice_id", ""),
            "resolved_entity_id": o.get("resolved_entity_id", ""),
            "speaker_resolution_status": o.get("speaker_resolution_status", ""),
            "speaker_resolution_confidence": o.get("speaker_resolution_confidence", ""),
            "speaker_display_name": o.get("speaker_display_name", ""),
            "channel_id": o.get("channel_id") or metadata.get("channel_id",""),
            "title": metadata.get("title") or o.get("title",""),
            "canonical_url": metadata.get("canonical_url") or o.get("canonical_url",""),
            "builder_version": BUILDER_VERSION,
            "text": o.get("text", ""),
        }

def _is_production_channel_path(path: Path):
    return any(re.fullmatch(r"YT\d+", p.name, re.I) for p in path.parents)

def transcript_files(root: Path):
    for p in root.rglob(f"*{CAPTION_SUFFIX}"):
        if _is_production_channel_path(p):
            yield p, iter_caption
    for p in root.rglob(DIARIZED_NAME):
        if _is_production_channel_path(p):
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
                    seg["speaker_id"], part, idx, seg.get("builder_version", BUILDER_VERSION)
                )
                current_unit_ids.add(uid)
                if uid in units:
                    units[uid]["last_seen_at"] = observed_at
                    units[uid]["source_status"] = "CURRENT"
                    units[uid]["builder_version"] = seg.get("builder_version", BUILDER_VERSION)
                    for mk in ("channel_id","platform_channel_id","channel_name","title","canonical_url","published_at","published_date","publication_precision"):
                        units[uid][mk]=seg.get(mk,units[uid].get(mk,""))
                    units[uid]["superseded_at"] = ""
                    continue
                units[uid] = {
                    "unit_id": uid,
                    "content_id": seg["content_id"],
                    "source_type": seg["source_type"],
                    "source_path": seg["source_path"],
                    "source_sha256": digest,
                    "channel_id": seg.get("channel_id",""),
                    "platform_channel_id": seg.get("platform_channel_id",""),
                    "channel_name": seg.get("channel_name",""),
                    "title": seg.get("title",""),
                    "canonical_url": seg.get("canonical_url",""),
                    "published_at": seg.get("published_at",""),
                    "published_date": seg.get("published_date",""),
                    "publication_precision": seg.get("publication_precision","UNKNOWN"),
                    "start_seconds": start,
                    "end_seconds": end,
                    "speaker_id": seg["speaker_id"],
                    "raw_speaker_id": seg.get("raw_speaker_id", seg["speaker_id"]),
                    "acoustic_cluster_id": seg.get("acoustic_cluster_id", ""),
                    "canonical_voice_id": seg.get("canonical_voice_id", ""),
                    "resolved_entity_id": seg.get("resolved_entity_id", ""),
                    "speaker_resolution_status": seg.get("speaker_resolution_status", ""),
                    "speaker_resolution_confidence": seg.get("speaker_resolution_confidence", ""),
                    "speaker_display_name": seg.get("speaker_display_name", ""),
                    "text": part,
                    "unit_index": idx,
                    "builder_version": seg.get("builder_version", BUILDER_VERSION),
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
        row["source_status"] = "SUPERSEDED"
        if not row.get("superseded_at"):
            row["superseded_at"] = observed_at

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
        "builder_version": BUILDER_VERSION,
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
