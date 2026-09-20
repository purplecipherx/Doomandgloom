#!/usr/bin/env python3
from __future__ import annotations

import argparse, csv, json, re
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

CAPTION_SEG_SUFFIX=".segments.jsonl"
DIARIZED_NAME="diarized_transcript.jsonl"
URL_RE=re.compile(r'https?://[^\s<>"\']+|\b(?:www\.)?[A-Za-z0-9.-]+\.(?:com|org|net|io|tv|news|co|us|gov|edu)\b',re.I)
CAP_RE=re.compile(r"\b(?:[A-Z][A-Za-z0-9&’'\.-]+(?:\s+|$)){1,6}")
STOP={"The","This","That","There","Here","And","But","For","With","From","Into","When","What","Why","How","Today","Yesterday","Tomorrow"}

def now(): return datetime.now(timezone.utc).isoformat()
def norm(s): return re.sub(r'[^a-z0-9]+',' ',s.lower()).strip()
def clean(s): return re.sub(r'\s+',' ',s).strip(" \t\r\n,.;:!?()[]{}\"'")

def classify(name,ctx):
    low=ctx.lower()
    rules=[
      ("media_show",r'\b(podcast|show|channel|radio|newsletter|substack|youtube|rumble|odysee|broadcast)\b'),
      ("event",r'\b(conference|summit|symposium|forum|congress|expo|webinar|workshop)\b'),
      ("government",r'\b(department|agency|commission|administration|bureau|ministry|senate|parliament|government|sec|cftc|ftc|fda|doj|fbi|cia|cdc|nih)\b'),
      ("organization",r'\b(foundation|institute|association|network|organization|council|committee|alliance|coalition|project|group|media|news|company|corp|corporation|inc|llc|ltd|nonprofit|charity)\b'),
      ("product",r'\b(report|course|book|film|documentary|device|supplement|membership|subscription|software|platform|service|system|model|program|app)\b')
    ]
    for typ,pat in rules:
        if re.search(pat,low,re.I): return typ
    if URL_RE.fullmatch(name): return "website"
    return "person_or_named_entity" if 2<=len(name.split())<=4 else "named_entity"

def iter_segments(root):
    for p in root.rglob(f"*{CAPTION_SEG_SUFFIX}"):
        vid=p.name[:-len(CAPTION_SEG_SUFFIX)]
        for line in p.read_text(encoding="utf-8",errors="replace").splitlines():
            try:o=json.loads(line)
            except:continue
            yield {"content_id":vid,"source_type":"youtube_caption","source_path":str(p),"start":o.get("start",""),"end":o.get("end",""),"speaker":"","text":o.get("text","")}
    for p in root.rglob(DIARIZED_NAME):
        for line in p.read_text(encoding="utf-8",errors="replace").splitlines():
            try:o=json.loads(line)
            except:continue
            yield {"content_id":o.get("video_id") or o.get("content_id") or "","source_type":"moji_diarized","source_path":str(p),"start":o.get("start_seconds",""),"end":o.get("end_seconds",""),"speaker":o.get("speaker_id",""),"text":o.get("text","")}

def mentions(text):
    out=[]
    for m in URL_RE.finditer(text):
        raw=clean(m.group(0))
        if raw: out.append((raw,"website",m.start(),m.end()))
    for m in CAP_RE.finditer(text):
        raw=clean(m.group(0))
        if not raw or raw in STOP or len(raw)<3: continue
        words=raw.split()
        while words and words[0] in STOP: words=words[1:]
        raw=" ".join(words)
        if raw: out.append((raw,None,m.start(),m.end()))
    return out

def read_master(path):
    if not path.exists(): return {}
    rows={}
    for r in csv.DictReader(path.open(encoding="utf-8-sig")):
        rows[r["candidate_key"]]=r
    return rows

def write_master(path,master):
    fields=["candidate_key","display_name","candidate_type","mention_count","distinct_content_count","distinct_source_count","speaker_count","first_seen_at","last_seen_at","sample_content_id","sample_snippet","review_status","approved_entity_id","review_notes","first_batch_id","last_batch_id"]
    with path.open("w",newline="",encoding="utf-8-sig") as f:
        w=csv.DictWriter(f,fieldnames=fields); w.writeheader()
        ordered=sorted(master.values(),key=lambda r:(-int(r["mention_count"]),-int(r["distinct_content_count"]),r["display_name"].lower()))
        w.writerows(ordered)

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--research-root",required=True)
    ap.add_argument("--output-dir",default="data/spider")
    ap.add_argument("--batch-id",required=True)
    ap.add_argument("--source-label",default="")
    args=ap.parse_args()

    root=Path(args.research_root).resolve()
    out=Path(args.output_dir).resolve(); out.mkdir(parents=True,exist_ok=True)
    run_dir=out/"runs"/args.batch_id
    if run_dir.exists():
        print(f"Spider batch already exists, refusing duplicate count: {run_dir}")
        return 0
    run_dir.mkdir(parents=True)

    agg={}; evidence=[]; co=defaultdict(int)
    segs=list(iter_segments(root))
    for seg in segs:
        text=seg["text"] or ""; keys=[]
        for raw,typ,s,e in mentions(text):
            ctx=text[max(0,s-140):min(len(text),e+140)].replace("\n"," ").strip()
            typ=typ or classify(raw,ctx); key=norm(raw)
            if not key: continue
            keys.append(key)
            r=agg.setdefault(key,{"display_name":raw,"candidate_type":typ,"mentions":0,"contents":set(),"sources":set(),"speakers":set(),"sample_content_id":seg["content_id"],"sample_snippet":ctx})
            r["mentions"]+=1; r["contents"].add(seg["content_id"]); r["sources"].add(seg["source_path"])
            if seg["speaker"]: r["speakers"].add(seg["speaker"])
            evidence.append({"batch_id":args.batch_id,"source_label":args.source_label,"candidate_key":key,"display_name":raw,"candidate_type":typ,**seg,"snippet":ctx})
        uk=sorted(set(keys))
        for i,a in enumerate(uk):
            for b in uk[i+1:]: co[(a,b)]+=1

    batch_rows=[]
    for key,r in agg.items():
        batch_rows.append({
          "candidate_key":key,"display_name":r["display_name"],"candidate_type":r["candidate_type"],
          "mention_count":r["mentions"],"distinct_content_count":len(r["contents"]),"distinct_source_count":len(r["sources"]),"speaker_count":len(r["speakers"]),
          "sample_content_id":r["sample_content_id"],"sample_snippet":r["sample_snippet"],"batch_id":args.batch_id,"source_label":args.source_label
        })
    batch_rows.sort(key=lambda r:(-r["mention_count"],-r["distinct_content_count"],r["display_name"].lower()))

    bf=["candidate_key","display_name","candidate_type","mention_count","distinct_content_count","distinct_source_count","speaker_count","sample_content_id","sample_snippet","batch_id","source_label"]
    with (run_dir/"mention_candidates.csv").open("w",newline="",encoding="utf-8-sig") as f:
        w=csv.DictWriter(f,fieldnames=bf); w.writeheader(); w.writerows(batch_rows)
    with (run_dir/"mention_evidence.jsonl").open("w",encoding="utf-8") as f:
        for r in evidence:f.write(json.dumps(r,ensure_ascii=False)+"\n")
    with (run_dir/"co_mentions.csv").open("w",newline="",encoding="utf-8-sig") as f:
        w=csv.DictWriter(f,fieldnames=["candidate_a","candidate_b","co_mention_count","batch_id"]); w.writeheader()
        for (a,b),n in sorted(co.items(),key=lambda x:-x[1]):w.writerow({"candidate_a":a,"candidate_b":b,"co_mention_count":n,"batch_id":args.batch_id})

    master_path=out/"mention_candidates.csv"; master=read_master(master_path); timestamp=now()
    for br in batch_rows:
        key=br["candidate_key"]
        if key in master:
            m=master[key]
            m["mention_count"]=str(int(m.get("mention_count") or 0)+int(br["mention_count"]))
            m["distinct_content_count"]=str(int(m.get("distinct_content_count") or 0)+int(br["distinct_content_count"]))
            m["distinct_source_count"]=str(int(m.get("distinct_source_count") or 0)+int(br["distinct_source_count"]))
            m["speaker_count"]=str(max(int(m.get("speaker_count") or 0),int(br["speaker_count"])))
            m["last_seen_at"]=timestamp; m["last_batch_id"]=args.batch_id
        else:
            master[key]={
              "candidate_key":key,"display_name":br["display_name"],"candidate_type":br["candidate_type"],
              "mention_count":str(br["mention_count"]),"distinct_content_count":str(br["distinct_content_count"]),"distinct_source_count":str(br["distinct_source_count"]),"speaker_count":str(br["speaker_count"]),
              "first_seen_at":timestamp,"last_seen_at":timestamp,"sample_content_id":br["sample_content_id"],"sample_snippet":br["sample_snippet"],
              "review_status":"new","approved_entity_id":"","review_notes":"","first_batch_id":args.batch_id,"last_batch_id":args.batch_id
            }
    write_master(master_path,master)

    manifest={"batch_id":args.batch_id,"source_label":args.source_label,"created_at":timestamp,"research_root":str(root),"segments_scanned":len(segs),"candidate_count":len(batch_rows),"mention_evidence_rows":len(evidence)}
    (run_dir/"spider_manifest.json").write_text(json.dumps(manifest,indent=2),encoding="utf-8")
    print(f"Spider batch {args.batch_id}: {len(segs)} segments, {len(batch_rows)} candidates")
    print(f"Master review queue: {master_path}")
    return 0

if __name__=="__main__": raise SystemExit(main())
