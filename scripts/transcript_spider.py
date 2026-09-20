#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

CAPTION_SEG_SUFFIX = ".segments.jsonl"
DIARIZED_NAME = "diarized_transcript.jsonl"
URL_RE = re.compile(r'https?://[^\s<>"\']+|\b(?:www\.)?[A-Za-z0-9.-]+\.(?:com|org|net|io|tv|news|co|us|gov|edu)\b', re.I)
CAP_RE = re.compile(r"\b(?:[A-Z][A-Za-z0-9&’'\.-]+(?:\s+|$)){1,6}")
CUE_RE = re.compile(
    r"\b(?:guest|with|joined by|speaking with|interview(?:ing)?|dr\.?|doctor|professor|mr\.?|mrs\.?|ms\.?|"
    r"podcast|channel|show|website|company|organization|organisation|foundation|institute|book|report|film|"
    r"conference|summit|sponsor(?:ed by)?|called|named)\s+"
    r"([A-Za-z0-9&’'\.-]+(?:\s+[A-Za-z0-9&’'\.-]+){1,6})",
    re.I,
)
STOP = {
    "the","this","that","there","here","and","but","for","with","from","into","when","what","why","how",
    "today","yesterday","tomorrow","we","you","they","he","she","it","our","your","their"
}

def now():
    return datetime.now(timezone.utc).isoformat()

def sha256(path: Path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()

def norm(s):
    return re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()

def clean(s):
    return re.sub(r"\s+", " ", s).strip(" \t\r\n,.;:!?()[]{}\"'")

def classify(name, ctx):
    rules = [
        ("media_show", r"\b(podcast|show|channel|radio|newsletter|substack|youtube|rumble|odysee|broadcast)\b"),
        ("event", r"\b(conference|summit|symposium|forum|congress|expo|webinar|workshop)\b"),
        ("government", r"\b(department|agency|commission|administration|bureau|ministry|senate|parliament|government|sec|cftc|ftc|fda|doj|fbi|cia|cdc|nih)\b"),
        ("organization", r"\b(foundation|institute|association|network|organization|organisation|council|committee|alliance|coalition|project|group|media|news|company|corp|corporation|inc|llc|ltd|nonprofit|charity)\b"),
        ("product", r"\b(report|course|book|film|documentary|device|supplement|membership|subscription|software|platform|service|system|model|program|app)\b"),
    ]
    for typ, pat in rules:
        if re.search(pat, ctx, re.I):
            return typ
    if URL_RE.fullmatch(name):
        return "website"
    return "person_or_named_entity" if 2 <= len(name.split()) <= 5 else "named_entity"

def load_known(repo_root: Path):
    aliases = {}
    entities_path = repo_root / "data" / "entities.csv"
    if entities_path.exists():
        for row in csv.DictReader(entities_path.open(encoding="utf-8-sig")):
            eid = (row.get("id") or "").strip()
            etype = (row.get("type") or "known_entity").strip()
            name = (row.get("name") or "").strip()
            if not name:
                continue
            parts = [x.strip() for x in re.split(r"\s*/\s*", name) if x.strip()]
            parts.append(name)
            for alias in parts:
                if len(alias) >= 3:
                    aliases[alias.lower()] = (alias, etype, eid)
    alias_path = repo_root / "data" / "entity_aliases.csv"
    if alias_path.exists():
        for row in csv.DictReader(alias_path.open(encoding="utf-8-sig")):
            alias = (row.get("alias") or "").strip()
            eid = (row.get("canonical_entity_id") or "").strip()
            if alias:
                aliases[alias.lower()] = (alias, "known_alias", eid)
    return aliases

def transcript_files(root: Path):
    for p in root.rglob(f"*{CAPTION_SEG_SUFFIX}"):
        yield p, "youtube_caption"
    for p in root.rglob(DIARIZED_NAME):
        yield p, "moji_diarized"

def read_segments(path: Path, source_type: str):
    if source_type == "youtube_caption":
        vid = path.name[:-len(CAPTION_SEG_SUFFIX)]
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            if not line.strip():
                continue
            try:
                o = json.loads(line)
            except Exception:
                continue
            yield {
                "content_id": vid,
                "source_type": source_type,
                "source_path": str(path),
                "start": o.get("start", ""),
                "end": o.get("end", ""),
                "speaker": "",
                "text": o.get("text", ""),
            }
    else:
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            if not line.strip():
                continue
            try:
                o = json.loads(line)
            except Exception:
                continue
            yield {
                "content_id": o.get("video_id") or o.get("content_id") or "",
                "source_type": source_type,
                "source_path": str(path),
                "start": o.get("start_seconds", ""),
                "end": o.get("end_seconds", ""),
                "speaker": o.get("speaker_id", ""),
                "text": o.get("text", ""),
            }

def extract_mentions(text, known):
    out = []
    occupied = []

    def add(raw, typ, start, end, canonical=""):
        raw = clean(raw)
        if not raw or len(raw) < 3:
            return
        key = norm(raw)
        if not key or key in STOP:
            return
        sig = (key, start, end)
        if any(x[:3] == sig for x in out):
            return
        out.append((key, raw, typ, start, end, canonical))
        occupied.append((start, end))

    # Known entities and aliases are matched case-insensitively, important for auto-captions.
    low = text.lower()
    for alias_low, (display, typ, eid) in known.items():
        pos = 0
        while True:
            i = low.find(alias_low, pos)
            if i < 0:
                break
            j = i + len(alias_low)
            left_ok = i == 0 or not low[i - 1].isalnum()
            right_ok = j == len(low) or not low[j].isalnum()
            if left_ok and right_ok:
                add(display, typ, i, j, eid)
            pos = max(j, i + 1)

    for m in URL_RE.finditer(text):
        add(m.group(0), "website", m.start(), m.end())

    # Proper-name heuristic for punctuated/manual transcripts.
    for m in CAP_RE.finditer(text):
        raw = clean(m.group(0))
        words = raw.split()
        while words and words[0].lower() in STOP:
            words = words[1:]
        raw = " ".join(words)
        if raw:
            add(raw, None, m.start(), m.end())

    # Cue-based extraction also works on lowercase auto-captions.
    for m in CUE_RE.finditer(text):
        raw = clean(m.group(1))
        # Stop runaway captures on common sentence/function words.
        words = raw.split()
        kept = []
        for w in words:
            if len(kept) >= 2 and w.lower() in {"and","but","because","who","that","which","where","when","to","for","with","from","about"}:
                break
            kept.append(w)
        raw = " ".join(kept[:6])
        if raw:
            add(raw, None, m.start(1), m.start(1) + len(raw))

    return out

def load_processed(path: Path):
    done = set()
    rows = []
    if path.exists():
        for r in csv.DictReader(path.open(encoding="utf-8-sig")):
            done.add((r.get("source_path", ""), r.get("sha256", "")))
            rows.append(r)
    return done, rows

def save_processed(path: Path, rows):
    fields = ["source_path","sha256","source_type","processed_at","batch_id","source_label"]
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)

def load_master(path: Path):
    if not path.exists():
        return {}
    return {r["candidate_key"]: r for r in csv.DictReader(path.open(encoding="utf-8-sig"))}

def all_run_evidence(out: Path):
    for p in (out / "runs").glob("*/mention_evidence.jsonl"):
        for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
            if not line.strip():
                continue
            try:
                yield json.loads(line)
            except Exception:
                continue

def rebuild_master(out: Path, old_master):
    stats = {}
    for e in all_run_evidence(out):
        key = e["candidate_key"]
        r = stats.setdefault(key, {
            "display_name": e["display_name"],
            "candidate_type": e["candidate_type"],
            "mentions": 0,
            "contents": set(),
            "sources": set(),
            "speakers": set(),
            "first_seen_at": e.get("processed_at") or "",
            "last_seen_at": e.get("processed_at") or "",
            "sample_content_id": e.get("content_id", ""),
            "sample_snippet": e.get("snippet", ""),
            "first_batch_id": e.get("batch_id", ""),
            "last_batch_id": e.get("batch_id", ""),
            "canonical_entity_id": e.get("canonical_entity_id", ""),
        })
        r["mentions"] += 1
        r["contents"].add(e.get("content_id", ""))
        r["sources"].add(e.get("source_path", ""))
        if e.get("speaker"):
            r["speakers"].add(e["speaker"])
        ts = e.get("processed_at") or ""
        if ts and (not r["first_seen_at"] or ts < r["first_seen_at"]):
            r["first_seen_at"] = ts
            r["first_batch_id"] = e.get("batch_id", "")
        if ts and ts >= r["last_seen_at"]:
            r["last_seen_at"] = ts
            r["last_batch_id"] = e.get("batch_id", "")

    fields = [
        "candidate_key","display_name","candidate_type","mention_count","distinct_content_count",
        "distinct_source_count","speaker_count","first_seen_at","last_seen_at","sample_content_id",
        "sample_snippet","review_status","approved_entity_id","review_notes","first_batch_id","last_batch_id"
    ]
    rows = []
    for key, s in stats.items():
        old = old_master.get(key, {})
        canonical = s.get("canonical_entity_id") or ""
        status = old.get("review_status") or ("existing" if canonical else "new")
        approved = old.get("approved_entity_id") or canonical
        rows.append({
            "candidate_key": key,
            "display_name": s["display_name"],
            "candidate_type": s["candidate_type"],
            "mention_count": s["mentions"],
            "distinct_content_count": len({x for x in s["contents"] if x}),
            "distinct_source_count": len({x for x in s["sources"] if x}),
            "speaker_count": len(s["speakers"]),
            "first_seen_at": s["first_seen_at"],
            "last_seen_at": s["last_seen_at"],
            "sample_content_id": s["sample_content_id"],
            "sample_snippet": s["sample_snippet"],
            "review_status": status,
            "approved_entity_id": approved,
            "review_notes": old.get("review_notes", ""),
            "first_batch_id": s["first_batch_id"],
            "last_batch_id": s["last_batch_id"],
        })
    rows.sort(key=lambda r: (-int(r["mention_count"]), -int(r["distinct_content_count"]), r["display_name"].lower()))
    path = out / "mention_candidates.csv"
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)
    return rows

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--research-root", required=True)
    ap.add_argument("--output-dir", default="data/spider")
    ap.add_argument("--batch-id", required=True)
    ap.add_argument("--source-label", default="")
    args = ap.parse_args()

    root = Path(args.research_root).resolve()
    out = Path(args.output_dir).resolve()
    out.mkdir(parents=True, exist_ok=True)
    run_dir = out / "runs" / args.batch_id
    if run_dir.exists():
        print(f"Spider batch already exists, refusing duplicate batch: {run_dir}")
        return 0
    run_dir.mkdir(parents=True)

    repo_root = out.parents[1] if len(out.parents) >= 2 else Path.cwd()
    known = load_known(repo_root)
    processed_path = out / "processed_transcripts.csv"
    processed, processed_rows = load_processed(processed_path)

    new_files = []
    skipped = []
    for path, source_type in transcript_files(root):
        digest = sha256(path)
        key = (str(path.resolve()), digest)
        if key in processed:
            skipped.append(str(path))
            continue
        new_files.append((path, source_type, digest))

    agg = {}
    evidence = []
    co = defaultdict(int)
    processed_at = now()

    for path, source_type, digest in new_files:
        for seg in read_segments(path, source_type):
            text = seg["text"] or ""
            keys = []
            for key, raw, typ, start, end, canonical in extract_mentions(text, known):
                ctx = text[max(0, start - 160):min(len(text), end + 160)].replace("\n", " ").strip()
                typ = typ or classify(raw, ctx)
                keys.append(key)
                r = agg.setdefault(key, {
                    "display_name": raw,
                    "candidate_type": typ,
                    "mentions": 0,
                    "contents": set(),
                    "sources": set(),
                    "speakers": set(),
                    "sample_content_id": seg["content_id"],
                    "sample_snippet": ctx,
                    "canonical_entity_id": canonical,
                })
                r["mentions"] += 1
                r["contents"].add(seg["content_id"])
                r["sources"].add(seg["source_path"])
                if seg["speaker"]:
                    r["speakers"].add(seg["speaker"])
                if canonical and not r["canonical_entity_id"]:
                    r["canonical_entity_id"] = canonical
                evidence.append({
                    "batch_id": args.batch_id,
                    "source_label": args.source_label,
                    "processed_at": processed_at,
                    "candidate_key": key,
                    "display_name": raw,
                    "candidate_type": typ,
                    "canonical_entity_id": canonical,
                    **seg,
                    "snippet": ctx,
                })
            uniq = sorted(set(keys))
            for i, a in enumerate(uniq):
                for b in uniq[i + 1:]:
                    co[(a, b)] += 1

        processed_rows.append({
            "source_path": str(path.resolve()),
            "sha256": digest,
            "source_type": source_type,
            "processed_at": processed_at,
            "batch_id": args.batch_id,
            "source_label": args.source_label,
        })

    batch_rows = []
    for key, r in agg.items():
        batch_rows.append({
            "candidate_key": key,
            "display_name": r["display_name"],
            "candidate_type": r["candidate_type"],
            "canonical_entity_id": r["canonical_entity_id"],
            "mention_count": r["mentions"],
            "distinct_content_count": len(r["contents"]),
            "distinct_source_count": len(r["sources"]),
            "speaker_count": len(r["speakers"]),
            "sample_content_id": r["sample_content_id"],
            "sample_snippet": r["sample_snippet"],
            "batch_id": args.batch_id,
            "source_label": args.source_label,
        })
    batch_rows.sort(key=lambda r: (-r["mention_count"], -r["distinct_content_count"], r["display_name"].lower()))

    bf = [
        "candidate_key","display_name","candidate_type","canonical_entity_id","mention_count",
        "distinct_content_count","distinct_source_count","speaker_count","sample_content_id",
        "sample_snippet","batch_id","source_label"
    ]
    with (run_dir / "mention_candidates.csv").open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=bf)
        w.writeheader()
        w.writerows(batch_rows)

    with (run_dir / "mention_evidence.jsonl").open("w", encoding="utf-8") as f:
        for r in evidence:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    with (run_dir / "co_mentions.csv").open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=["candidate_a","candidate_b","co_mention_count","batch_id"])
        w.writeheader()
        for (a, b), n in sorted(co.items(), key=lambda x: -x[1]):
            w.writerow({"candidate_a": a, "candidate_b": b, "co_mention_count": n, "batch_id": args.batch_id})

    save_processed(processed_path, processed_rows)
    old_master = load_master(out / "mention_candidates.csv")
    master_rows = rebuild_master(out, old_master)

    manifest = {
        "batch_id": args.batch_id,
        "source_label": args.source_label,
        "created_at": processed_at,
        "research_root": str(root),
        "transcript_files_new": len(new_files),
        "transcript_files_skipped_already_processed": len(skipped),
        "segments_scanned": sum(1 for _ in evidence),
        "candidate_count_this_batch": len(batch_rows),
        "master_candidate_count": len(master_rows),
        "mention_evidence_rows": len(evidence),
        "known_aliases_loaded": len(known),
    }
    (run_dir / "spider_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    print(f"Spider batch {args.batch_id}: {len(new_files)} new transcript file(s), {len(skipped)} already processed")
    print(f"Candidates this batch: {len(batch_rows)}; master queue: {len(master_rows)}")
    print(out / "mention_candidates.csv")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
