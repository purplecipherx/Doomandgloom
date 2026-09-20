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

from build_research_ledger import reconstruct_caption_segments

CAPTION_SEG_SUFFIX = ".segments.jsonl"
DIARIZED_NAME = "diarized_transcript.jsonl"
URL_RE = re.compile(r'https?://[^\s<>"\']+|\b(?:www\.)?[A-Za-z0-9.-]+\.(?:com|org|net|io|tv|news|co|us|gov|edu)\b', re.I)

# Proper-name spans. Unknown single-token names are handled conservatively below;
# multi-token title-case spans are much less likely to be sentence-initial filler.
CAP_RE = re.compile(
    r"\b[A-Z][A-Za-z0-9&’'\.-]*"
    r"(?:\s+(?:(?:[A-Z][A-Za-z0-9&’'\.-]*)|of|the|and|for)){0,5}\b"
)

PERSON_CUE_RE = re.compile(
    r"\b(?:guest(?:\s+is)?|joined\s+by|speaking\s+with|interview(?:ing|\s+with)?|"
    r"dr\.?|doctor|professor|mr\.?|mrs\.?|ms\.?)\s+"
    r"([A-Za-z0-9&’'\.-]+(?:\s+[A-Za-z0-9&’'\.-]+){0,4})",
    re.I,
)

ENTITY_CUE_RE = re.compile(
    r"\b(?P<kind>podcast|channel|website|company|organization|organisation|foundation|institute|"
    r"book|report|film|documentary|conference|summit|project|platform|service|sponsor)\s+"
    r"(?:(?P<intro>called|named|titled|known\s+as)\s+)?"
    r"(?P<name>[A-Za-z0-9&’'\.-]+(?:\s+[A-Za-z0-9&’'\.-]+){0,5})",
    re.I,
)

STOP = {
    "a","an","the","this","that","these","those","there","here","and","but","or","so","because","for","with",
    "from","into","when","what","why","how","who","where","today","yesterday","tomorrow","we","you","they","he",
    "she","it","i","me","my","our","your","their","his","her","its","is","are","was","were","be","been","being",
    "have","has","had","do","does","did","can","could","will","would","should","may","might","must","not","no",
    "yes","yeah","mhm","uh","um","right","okay","ok","well","now","then","just","really","actually","basically",
    "exactly","absolutely","probably","maybe","anyway","again","all","one","two","three","four","five","look","see",
    "sure","good","great","wow"
}

BAD_SINGLE = STOP | {
    "american","chinese","iranian","russian","british","european","global","local","federal","state","national",
}

BAD_CUE_START = STOP | {
    "someone","somebody","something","people","person","thing","things","way","kind","lot","number","new","same",
    "in","on","at","to","from","about","into","over","under","near","around","through","taking","place","based",
}

CUE_STOP = {
    "because","who","that","which","where","when","if","then","so","but","however","although","though","while",
    "was","were","is","are","has","have","had","will","would","can","could","should","may","might","must",
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



CONNECTOR_WORDS = {"of","the","and","for","de","del","van","von","la","le","&"}
CONTRACTION_RE = re.compile(
    r"^(?:i|we|you|they|he|she|it|that|what|there|here)[’']?(?:m|re|ve|d|ll|s|t)?$",
    re.I,
)

def _candidate_tokens(name):
    return [x for x in re.split(r"\s+", clean(name)) if x]

def _token_is_proper(token):
    t = token.strip("()[]{}\"'")
    if not t:
        return False
    if t.lower() in CONNECTOR_WORDS:
        return True
    if t.isupper() and 2 <= len(t) <= 12:
        return True
    if re.fullmatch(r"[A-Z][A-Za-z0-9&’'-]*", t):
        return True
    return False

def candidate_eligible(canonical, name, candidate_type, mentions, content_count, signals, prior_status=""):
    """High-precision review queue gate. Raw mention evidence is never discarded."""
    signals = set(signals or [])
    status = (prior_status or "").strip().lower()
    if canonical or status in {"approved", "existing", "accepted"}:
        return True
    if "url" in signals or candidate_type == "website":
        return True

    raw = clean(name)
    if not raw or len(raw) < 3:
        return False

    # Proper-name regex must never bridge sentence punctuation. Strong cue rules
    # are allowed to contain abbreviations such as "Dr." but plain proper_case is not.
    if "proper_case" in signals and re.search(r"[.!?]", raw):
        return False

    words = _candidate_tokens(raw)
    if not words:
        return False

    first = words[0].lower().strip(".,;:!?()[]{}\"'").replace("’", "'")
    last = words[-1].lower().strip(".,;:!?()[]{}\"'").replace("’", "'")

    if first in STOP or first in BAD_CUE_START or CONTRACTION_RE.fullmatch(first):
        return False
    if last in STOP or last in CUE_STOP or CONTRACTION_RE.fullmatch(last):
        return False

    # Strong typed/introduction cues are useful even when auto-captions lowercase names.
    if any(sig.startswith("cue_person") for sig in signals):
        return len(words) <= 5
    if any(sig.startswith("cue_entity") for sig in signals):
        return 1 <= len(words) <= 6

    if "proper_case" not in signals:
        return False

    # One-token unknowns are retained only when repeated independently or acronym-like.
    if len(words) == 1:
        token = words[0]
        if CONTRACTION_RE.fullmatch(token):
            return False
        acronym_like = token.isupper() and 2 <= len(token) <= 12
        internal_cap = any(c.isupper() for c in token[1:])
        repeated = int(content_count) >= 2
        return acronym_like or internal_cap or repeated

    # Multi-token proper names must actually have a proper-name shape.
    if len(words) > 6:
        return False
    return all(_token_is_proper(w) for w in words)

def triage(canonical, candidate_type, mentions, content_count, speaker_count, signals):
    signals = set(signals or [])
    score = 0
    if canonical:
        score += 100
    if candidate_type == "website":
        score += 30
    if "known" in signals:
        score += 100
    if "url" in signals:
        score += 25
    if any(sig.startswith("cue_") for sig in signals):
        score += 25
    if "proper_case" in signals:
        score += 8
    score += min(20, int(mentions) * 2)
    score += min(30, int(content_count) * 5)
    score += min(10, int(speaker_count) * 2)
    if canonical:
        priority = "EXISTING"
    elif score >= 45:
        priority = "HIGH"
    elif score >= 25:
        priority = "MEDIUM"
    else:
        priority = "LOW"
    return score, priority

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
        segments,_stats = reconstruct_caption_segments(path)
        for o in segments:
            yield {
                "content_id": vid,
                "source_type": source_type,
                "source_path": str(path),
                "start": o.get("start_seconds", ""),
                "end": o.get("end_seconds", ""),
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

def _trim_cue_name(raw, max_words=5):
    words = clean(raw).split()
    if not words:
        return ""
    if words[0].lower().replace("’", "'") in BAD_CUE_START:
        return ""
    kept = []
    for w in words[:max_words]:
        had_sentence_end = bool(re.search(r"[.!?]$", w))
        lw = w.lower().strip(".,;:!?()[]{}\"'").replace("’", "'")
        if kept and lw in CUE_STOP:
            break
        cleaned_word = w.strip(".,;:!?()[]{}\"'")
        if cleaned_word:
            kept.append(cleaned_word)
        if had_sentence_end:
            break
    while kept and kept[-1].lower().strip(".,;:!?()[]{}\"'").replace("’", "'") in STOP:
        kept.pop()
    if not kept:
        return ""
    # Lowercase auto-caption cue captures need at least two tokens unless the cue
    # itself is an honorific/person cue (handled separately).
    return " ".join(kept)


def extract_mentions(text, known):
    out = []
    occupied = []

    def add(raw, typ, start, end, canonical="", signal="heuristic"):
        raw = clean(raw)
        if not raw or len(raw) < 3:
            return
        key = norm(raw)
        if not key or key in STOP:
            return
        sig = (key, start, end)
        if any(x[:3] == sig for x in out):
            return
        out.append((key, raw, typ, start, end, canonical, signal))
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
                add(display, typ, i, j, eid, "known")
            pos = max(j, i + 1)

    for m in URL_RE.finditer(text):
        add(m.group(0), "website", m.start(), m.end(), "", "url")

    # Proper-name heuristic for punctuated/manual transcripts.
    for m in CAP_RE.finditer(text):
        raw = clean(m.group(0))
        words = raw.split()
        while words and words[0].lower().replace("’", "'") in STOP:
            words = words[1:]
        raw = " ".join(words)
        if not raw:
            continue

        if len(words) == 1:
            token = words[0].strip(".,;:!?()[]{}\"'")
            low_token = token.lower().replace("’", "'")
            # Sentence-initial discourse words and common adjectives created most
            # of the previous false positives. Keep one-token unknowns only when
            # they look acronym-like/internal-capitalized or occur away from a
            # likely sentence boundary.
            acronym_like = token.isupper() and 2 <= len(token) <= 12
            internal_cap = any(c.isupper() for c in token[1:])
            prev = text[:m.start()].rstrip()
            mid_sentence = bool(prev) and prev[-1] not in ".!?\n>"
            if low_token in BAD_SINGLE:
                continue
            if not (acronym_like or internal_cap or mid_sentence):
                continue

        add(raw, None, m.start(), m.end(), "", "proper_case")

    # Strong person cues. Unlike the old generic "with" rule, these have explicit
    # introduction/interview/title semantics.
    for m in PERSON_CUE_RE.finditer(text):
        raw = _trim_cue_name(m.group(1), max_words=4)
        if raw:
            add(raw, "person", m.start(1), m.start(1) + len(raw), "", "cue_person")

    # Typed entity cues. These retain lowercase auto-caption discovery without
    # treating arbitrary text following "with/show/report" as an entity.
    kind_type = {
        "podcast": "media_show", "channel": "media_show",
        "website": "website", "company": "organization",
        "organization": "organization", "organisation": "organization",
        "foundation": "organization", "institute": "organization",
        "book": "product", "report": "product", "film": "product",
        "documentary": "product", "conference": "event", "summit": "event",
        "project": "organization", "platform": "product", "service": "product",
        "sponsor": "organization",
    }
    for m in ENTITY_CUE_RE.finditer(text):
        raw = _trim_cue_name(m.group("name"), max_words=5)
        if not raw:
            continue
        words = raw.split()
        intro = bool(m.group("intro"))
        visible_proper = any(_token_is_proper(w) and w.lower() not in CONNECTOR_WORDS for w in words)
        url_like = bool(URL_RE.fullmatch(raw))
        # Generic noun-following text ("website in Arizona", "book on X",
        # "conference taking place...") is not a named entity. Lowercase names are
        # still accepted after an explicit naming construction such as "called".
        if not (intro or visible_proper or url_like):
            continue
        if len(words) < 2 and not (intro or visible_proper or url_like):
            continue
        kind = m.group("kind").lower()
        signal = "cue_entity_named" if intro else "cue_entity"
        add(raw, kind_type.get(kind, "named_entity"), m.start("name"), m.start("name") + len(raw), "", signal)

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
        manifest_path = p.parent / "spider_manifest.json"
        if manifest_path.exists():
            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                if manifest.get("superseded"):
                    continue
            except Exception:
                pass
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
            "signals": set(),
        })
        r["mentions"] += 1
        r["contents"].add(e.get("content_id", ""))
        r["sources"].add(e.get("source_path", ""))
        if e.get("speaker"):
            r["speakers"].add(e["speaker"])
        if e.get("signal"):
            r["signals"].add(e["signal"])
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
        "sample_snippet","triage_score","review_priority","signal_types","review_status",
        "approved_entity_id","review_notes","first_batch_id","last_batch_id"
    ]
    rows = []
    for key, s in stats.items():
        old = old_master.get(key, {})
        canonical = s.get("canonical_entity_id") or ""
        status = old.get("review_status") or ("existing" if canonical else "new")
        approved = old.get("approved_entity_id") or canonical
        content_count = len({x for x in s["contents"] if x})
        speaker_count = len(s["speakers"])
        score, priority = triage(canonical, s["candidate_type"], s["mentions"], content_count, speaker_count, s["signals"])
        if not candidate_eligible(
            canonical, s["display_name"], s["candidate_type"], s["mentions"],
            content_count, s["signals"], old.get("review_status", "")
        ):
            continue
        rows.append({
            "candidate_key": key,
            "display_name": s["display_name"],
            "candidate_type": s["candidate_type"],
            "mention_count": s["mentions"],
            "distinct_content_count": content_count,
            "distinct_source_count": len({x for x in s["sources"] if x}),
            "speaker_count": speaker_count,
            "first_seen_at": s["first_seen_at"],
            "last_seen_at": s["last_seen_at"],
            "sample_content_id": s["sample_content_id"],
            "sample_snippet": s["sample_snippet"],
            "triage_score": score,
            "review_priority": priority,
            "signal_types": ";".join(sorted(s["signals"])),
            "review_status": status,
            "approved_entity_id": approved,
            "review_notes": old.get("review_notes", ""),
            "first_batch_id": s["first_batch_id"],
            "last_batch_id": s["last_batch_id"],
        })
    priority_order = {"EXISTING": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}
    rows.sort(key=lambda r: (
        priority_order.get(r["review_priority"], 9),
        -int(r["triage_score"]),
        -int(r["mention_count"]),
        -int(r["distinct_content_count"]),
        r["display_name"].lower(),
    ))
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
    segment_count = 0

    for path, source_type, digest in new_files:
        for seg in read_segments(path, source_type):
            segment_count += 1
            text = seg["text"] or ""
            keys = []
            for key, raw, typ, start, end, canonical, signal in extract_mentions(text, known):
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
                    "signals": set(),
                })
                r["mentions"] += 1
                r["contents"].add(seg["content_id"])
                r["sources"].add(seg["source_path"])
                if seg["speaker"]:
                    r["speakers"].add(seg["speaker"])
                if canonical and not r["canonical_entity_id"]:
                    r["canonical_entity_id"] = canonical
                r["signals"].add(signal)
                evidence.append({
                    "batch_id": args.batch_id,
                    "source_label": args.source_label,
                    "processed_at": processed_at,
                    "candidate_key": key,
                    "display_name": raw,
                    "candidate_type": typ,
                    "canonical_entity_id": canonical,
                    "signal": signal,
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

    raw_candidate_count = len(agg)
    batch_rows = []
    for key, r in agg.items():
        content_count = len(r["contents"])
        speaker_count = len(r["speakers"])
        score, priority = triage(
            r["canonical_entity_id"], r["candidate_type"], r["mentions"],
            content_count, speaker_count, r["signals"]
        )
        if not candidate_eligible(
            r["canonical_entity_id"], r["display_name"], r["candidate_type"],
            r["mentions"], content_count, r["signals"]
        ):
            continue
        batch_rows.append({
            "candidate_key": key,
            "display_name": r["display_name"],
            "candidate_type": r["candidate_type"],
            "canonical_entity_id": r["canonical_entity_id"],
            "mention_count": r["mentions"],
            "distinct_content_count": content_count,
            "distinct_source_count": len(r["sources"]),
            "speaker_count": speaker_count,
            "triage_score": score,
            "review_priority": priority,
            "signal_types": ";".join(sorted(r["signals"])),
            "sample_content_id": r["sample_content_id"],
            "sample_snippet": r["sample_snippet"],
            "batch_id": args.batch_id,
            "source_label": args.source_label,
        })
    priority_order = {"EXISTING": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}
    batch_rows.sort(key=lambda r: (
        priority_order.get(r["review_priority"], 9),
        -int(r["triage_score"]),
        -int(r["mention_count"]),
        r["display_name"].lower(),
    ))

    bf = [
        "candidate_key","display_name","candidate_type","canonical_entity_id","mention_count",
        "distinct_content_count","distinct_source_count","speaker_count","triage_score",
        "review_priority","signal_types","sample_content_id","sample_snippet","batch_id","source_label"
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
        "segments_scanned": segment_count,
        "raw_candidate_keys_this_batch": raw_candidate_count,
        "candidate_count_this_batch": len(batch_rows),
        "master_candidate_count": len(master_rows),
        "mention_evidence_rows": len(evidence),
        "known_aliases_loaded": len(known),
        "priority_counts": {
            p: sum(1 for r in batch_rows if r["review_priority"] == p)
            for p in ("EXISTING", "HIGH", "MEDIUM", "LOW")
        },
    }
    (run_dir / "spider_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    print(f"Spider batch {args.batch_id}: {len(new_files)} new transcript file(s), {len(skipped)} already processed")
    print(f"Raw candidate keys: {raw_candidate_count}; review candidates: {len(batch_rows)}; master queue: {len(master_rows)}")
    print(out / "mention_candidates.csv")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
