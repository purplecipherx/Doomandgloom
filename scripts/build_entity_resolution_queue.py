#!/usr/bin/env python3
from __future__ import annotations

import argparse,csv,json,re
from collections import defaultdict
from difflib import SequenceMatcher
from pathlib import Path

def norm(s):
    s=str(s or "").strip().lower()
    s=s.replace("’","'")
    s=re.sub(r"[^a-z0-9@._' -]+"," ",s)
    s=re.sub(r"\s+"," ",s).strip()
    return s

def sim(a,b):
    return SequenceMatcher(None,norm(a),norm(b)).ratio()

def read_csv(path):
    p=Path(path)
    if not p.exists(): return []
    return list(csv.DictReader(p.open(encoding="utf-8-sig")))

def write_csv(path,rows,fields):
    p=Path(path); p.parent.mkdir(parents=True,exist_ok=True)
    with p.open("w",newline="",encoding="utf-8-sig") as f:
        w=csv.DictWriter(f,fieldnames=fields);w.writeheader()
        for r in rows:w.writerow({k:r.get(k,"") for k in fields})

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--mentions",default="data/analysis/mentions.csv")
    ap.add_argument("--entities",default="data/entities.csv")
    ap.add_argument("--aliases",default="data/entity_aliases.csv")
    ap.add_argument("--output",default="data/analysis/entity_resolution_queue.csv")
    ap.add_argument("--top-k",type=int,default=5)
    ap.add_argument("--min-similarity",type=float,default=0.62)
    args=ap.parse_args()

    mentions=read_csv(args.mentions)
    entities=read_csv(args.entities)
    aliases=read_csv(args.aliases)

    names=[]
    for e in entities:
        eid=e.get("id","")
        name=e.get("name","") or e.get("display_name","")
        if eid and name:names.append((eid,name,"entity"))
    for a in aliases:
        eid=a.get("entity_id","") or a.get("canonical_entity_id","")
        alias=a.get("alias","") or a.get("name","")
        if eid and alias:names.append((eid,alias,"alias"))

    agg=defaultdict(lambda:{"count":0,"contents":set(),"examples":[],"entity_type":"","correction_candidates":defaultdict(int)})
    for m in mentions:
        if m.get("canonical_entity_id"):
            continue
        surface=m.get("surface","")
        if not surface:continue
        key=norm(surface)
        if not key:continue
        d=agg[key];d["count"]+=1
        if m.get("content_id"):d["contents"].add(m["content_id"])
        if len(d["examples"])<5:d["examples"].append(surface)
        if m.get("entity_type"):d["entity_type"]=m["entity_type"]
        cc=m.get("correction_candidate","")
        if cc:d["correction_candidates"][cc]+=1

    out=[]
    k=max(1,args.top_k)
    for key,d in agg.items():
        display=max(d["examples"],key=len) if d["examples"] else key
        scored=[]
        candidate_names=set(d["correction_candidates"])
        for cc in candidate_names:
            for eid,name,kind in names:
                score=max(sim(cc,name),sim(display,name))
                if score>=args.min_similarity:scored.append((score,eid,name,kind,"semantic_correction"))
        for eid,name,kind in names:
            score=sim(display,name)
            if score>=args.min_similarity:scored.append((score,eid,name,kind,"surface_similarity"))
        best={}
        for score,eid,name,kind,basis in scored:
            old=best.get(eid)
            if old is None or score>old[0]:best[eid]=(score,name,kind,basis)
        ranked=sorted([(v[0],eid,v[1],v[2],v[3]) for eid,v in best.items()],reverse=True)[:k]
        out.append({
            "surface":display,"normalized_surface":key,"entity_type":d["entity_type"],
            "mention_count":d["count"],"distinct_content_count":len(d["contents"]),
            "semantic_correction_candidates_json":json.dumps(d["correction_candidates"],ensure_ascii=False),
            "candidate_matches_json":json.dumps([
                {"entity_id":eid,"name":name,"similarity":round(score,4),"name_kind":kind,"basis":basis}
                for score,eid,name,kind,basis in ranked
            ],ensure_ascii=False),
            "top_candidate_entity_id":ranked[0][1] if ranked else "",
            "top_candidate_name":ranked[0][2] if ranked else "",
            "top_similarity":round(ranked[0][0],4) if ranked else "",
            "status":"PENDING"
        })
    out.sort(key=lambda r:(-int(r["distinct_content_count"]),-int(r["mention_count"]),r["surface"].lower()))
    fields=[
        "surface","normalized_surface","entity_type","mention_count","distinct_content_count",
        "semantic_correction_candidates_json","candidate_matches_json","top_candidate_entity_id",
        "top_candidate_name","top_similarity","status"
    ]
    write_csv(args.output,out,fields)
    print(json.dumps({"unresolved_surfaces":len(out),"output":str(Path(args.output).resolve())},indent=2))
    return 0

if __name__=="__main__":
    raise SystemExit(main())
