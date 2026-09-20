#!/usr/bin/env python3
"""
Doomandgloom transcript spider.

Scans completed transcript text for named mentions and creates a human-review queue.
It does not automatically promote candidates into the investigation graph.
"""
from __future__ import annotations
import argparse, csv, json, re, hashlib
from collections import defaultdict
from pathlib import Path
from datetime import datetime, timezone

CAPTION_SEG_SUFFIX = ".segments.jsonl"
DIARIZED_NAME = "diarized_transcript.jsonl"

# Conservative heuristics. This is discovery, not proof.
URL_RE = re.compile(r'https?://[^\s<>"\']+|\b(?:www\.)?[A-Za-z0-9.-]+\.(?:com|org|net|io|tv|news|co|us|gov|edu)\b', re.I)
CAP_RE = re.compile(r'\b(?:[A-Z][A-Za-z0-9&’\'\.-]+(?:\s+|$)){1,6}')
KEYWORD_PATTERNS = {
    "organization": re.compile(r'\b(?:foundation|institute|association|network|organization|organisation|council|committee|alliance|coalition|project|group|media|news|report|economics|health|defense|defence|university|college|company|corp\.?|corporation|inc\.?|llc|ltd\.?|nonprofit|charity)\b', re.I),
    "media_show": re.compile(r'\b(?:podcast|show|channel|radio|network|newsletter|substack|youtube|rumble|odysee|broadcast|interview series)\b', re.I),
    "event": re.compile(r'\b(?:conference|summit|symposium|forum|congress|expo|event|workshop|webinar)\b', re.I),
    "product": re.compile(r'\b(?:report|course|book|film|documentary|device|supplement|membership|subscription|software|platform|service|system|model|program|programme|app)\b', re.I),
    "government": re.compile(r'\b(?:department|agency|commission|administration|bureau|ministry|senate|house|parliament|government|federal reserve|central bank|sec|cftc|ftc|fda|doj|fbi|cia|cdc|nih)\b', re.I),
}

STOPWORDS = {
    "The","This","That","There","Here","And","But","For","With","From","Into","When","What","Why","How",
    "I","We","You","He","She","They","It","A","An","In","On","Of","To","Is","Are","Was","Were","Be","Been",
    "Today","Yesterday","Tomorrow","Monday","Tuesday","Wednesday","Thursday","Friday","Saturday","Sunday",
    "United States","United Kingdom"
}

def utc_now():
    return datetime.now(timezone.utc).isoformat()

def norm_name(s: str) -> str:
    s = re.sub(r'\s+', ' ', s).strip(" \t\r\n,.;:!?()[]{}\"'")
    return s

def classify(name: str, context: str) -> str:
    low = context.lower()
    for typ, rx in KEYWORD_PATTERNS.items():
        if rx.search(context):
            return typ
    if URL_RE.search(name):
        return "website"
    # Default proper-name discovery bucket.
    words = name.split()
    if 2 <= len(words) <= 4:
        return "person_or_named_entity"
    return "named_entity"

def iter_caption_segments(root: Path):
    for p in root.rglob(f"*{CAPTION_SEG_SUFFIX}"):
        vid = p.name[:-len(CAPTION_SEG_SUFFIX)]
        for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
            if not line.strip():
                continue
            try:
                o=json.loads(line)
            except Exception:
                continue
            yield {
                "content_id": vid,
                "source_type":"youtube_caption",
                "source_path":str(p),
                "start":o.get("start",""),
                "end":o.get("end",""),
                "speaker":"",
                "text":o.get("text",""),
            }

def iter_diarized(root: Path):
    for p in root.rglob(DIARIZED_NAME):
        for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
            if not line.strip():
                continue
            try:
                o=json.loads(line)
            except Exception:
                continue
            yield {
                "content_id":o.get("video_id") or o.get("content_id") or "",
                "source_type":"moji_diarized",
                "source_path":str(p),
                "start":o.get("start_seconds",""),
                "end":o.get("end_seconds",""),
                "speaker":o.get("speaker_id",""),
                "text":o.get("text",""),
            }

def extract_mentions(text: str):
    found = []
    # URLs/domains.
    for m in URL_RE.finditer(text):
        raw = norm_name(m.group(0))
        if raw:
            found.append((raw,"website",m.start(),m.end()))
    # Proper-name spans.
    for m in CAP_RE.finditer(text):
        raw = norm_name(m.group(0))
        if not raw or raw in STOPWORDS or len(raw) < 3:
            continue
        if raw.isupper() and len(raw) <= 2:
            continue
        # trim likely sentence-leading garbage
        words=raw.split()
        while words and words[0] in STOPWORDS:
            words=words[1:]
        raw=" ".join(words)
        if not raw or raw in STOPWORDS:
            continue
        found.append((raw,None,m.start(),m.end()))
    return found

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--research-root",default="research")
    ap.add_argument("--output-dir",default="data/spider")
    ap.add_argument("--batch-id",default="")
    ap.add_argument("--min-mentions",type=int,default=1)
    args=ap.parse_args()

    research=Path(args.research_root).resolve()
    out=Path(args.output_dir).resolve()
    out.mkdir(parents=True,exist_ok=True)
    batch_id=args.batch_id or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    agg={}
    evidence=[]
    co_counts=defaultdict(int)

    segments=list(iter_caption_segments(research)) + list(iter_diarized(research))
    for seg in segments:
        text=seg["text"] or ""
        mentions=extract_mentions(text)
        names=[]
        for raw,typ,s,e in mentions:
            ctx=text[max(0,s-120):min(len(text),e+120)]
            typ=typ or classify(raw,ctx)
            key=re.sub(r'[^a-z0-9]+',' ',raw.lower()).strip()
            if not key:
                continue
            names.append(key)
            rec=agg.setdefault(key,{
                "candidate_key":key,
                "display_name":raw,
                "candidate_type":typ,
                "mention_count":0,
                "content_ids":set(),
                "source_paths":set(),
                "first_seen":None,
                "last_seen":None,
                "speakers":set(),
                "sample_snippet":"",
                "sample_content_id":"",
                "status":"new",
            })
            rec["mention_count"]+=1
            rec["content_ids"].add(seg["content_id"])
            rec["source_paths"].add(seg["source_path"])
            if seg.get("speaker"):
                rec["speakers"].add(seg["speaker"])
            if not rec["sample_snippet"]:
                rec["sample_snippet"]=ctx.replace("\n"," ").strip()
                rec["sample_content_id"]=seg["content_id"]
            ts = str(seg["start"])
            if rec["first_seen"] is None:
                rec["first_seen"]=ts
            rec["last_seen"]=ts
            evidence.append({
                "batch_id":batch_id,
                "candidate_key":key,
                "display_name":raw,
                "candidate_type":typ,
                "content_id":seg["content_id"],
                "source_type":seg["source_type"],
                "source_path":seg["source_path"],
                "start":seg["start"],
                "end":seg["end"],
                "speaker":seg["speaker"],
                "snippet":ctx.replace("\n"," ").strip(),
            })
        uniq=sorted(set(names))
        for i,a in enumerate(uniq):
            for b in uniq[i+1:]:
                co_counts[(a,b)] += 1

    candidates=[]
    for key,rec in agg.items():
        if rec["mention_count"] < args.min_mentions:
            continue
        candidates.append({
            "candidate_key":key,
            "display_name":rec["display_name"],
            "candidate_type":rec["candidate_type"],
            "mention_count":rec["mention_count"],
            "distinct_content_count":len(rec["content_ids"]),
            "distinct_source_count":len(rec["source_paths"]),
            "speaker_count":len(rec["speakers"]),
            "first_seen":rec["first_seen"] or "",
            "last_seen":rec["last_seen"] or "",
            "sample_content_id":rec["sample_content_id"],
            "sample_snippet":rec["sample_snippet"],
            "review_status":"new",
            "approved_entity_id":"",
            "review_notes":"",
            "batch_id":batch_id,
        })

    candidates.sort(key=lambda r:(-r["mention_count"],-r["distinct_content_count"],r["display_name"].lower()))

    cand_path=out/"mention_candidates.csv"
    fields=[
        "candidate_key","display_name","candidate_type","mention_count","distinct_content_count",
        "distinct_source_count","speaker_count","first_seen","last_seen","sample_content_id",
        "sample_snippet","review_status","approved_entity_id","review_notes","batch_id"
    ]
    with cand_path.open("w",newline="",encoding="utf-8-sig") as f:
        w=csv.DictWriter(f,fieldnames=fields); w.writeheader(); w.writerows(candidates)

    ev_path=out/"mention_evidence.jsonl"
    with ev_path.open("w",encoding="utf-8") as f:
        for r in evidence:
            f.write(json.dumps(r,ensure_ascii=False)+"\n")

    co_path=out/"co_mentions.csv"
    with co_path.open("w",newline="",encoding="utf-8-sig") as f:
        fields2=["candidate_a","candidate_b","co_mention_count","batch_id"]
        w=csv.DictWriter(f,fieldnames=fields2); w.writeheader()
        for (a,b),n in sorted(co_counts.items(), key=lambda kv:-kv[1]):
            w.writerow({"candidate_a":a,"candidate_b":b,"co_mention_count":n,"batch_id":batch_id})

    manifest={
        "batch_id":batch_id,
        "created_at":utc_now(),
        "research_root":str(research),
        "segments_scanned":len(segments),
        "candidate_count":len(candidates),
        "mention_evidence_rows":len(evidence),
        "outputs":[str(cand_path),str(ev_path),str(co_path)]
    }
    (out/"spider_manifest.json").write_text(json.dumps(manifest,indent=2),encoding="utf-8")
    print(f"Spider scanned {len(segments)} transcript segments")
    print(f"Candidates: {len(candidates)}")
    print(cand_path)

if __name__=="__main__":
    main()
