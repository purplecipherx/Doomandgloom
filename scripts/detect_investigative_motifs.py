#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

NEGATIVE={"CRITICIZES","DISPUTES","ACCUSES","WARNS_AGAINST","RIDICULES","DISTANCES_FROM","CONTRADICTS","OPPOSES"}
POSITIVE={"PRAISES","ENDORSES","SUPPORTS","DEFENDS","AGREES_WITH","PROMOTES","RECOMMENDS"}

def now():
    return datetime.now(timezone.utc).isoformat()

def read_csv(path:Path):
    if not path.exists(): return []
    return list(csv.DictReader(path.open(encoding="utf-8-sig")))

def clean(s): return str(s or "").strip()

def mid(prefix,*parts):
    raw="\x1f".join(clean(x) for x in parts)
    return prefix+hashlib.sha256(raw.encode("utf-8")).hexdigest()[:20].upper()

def write_csv(path,rows,fields):
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open("w",newline="",encoding="utf-8-sig") as f:
        w=csv.DictWriter(f,fieldnames=fields); w.writeheader()
        for r in rows:w.writerow({k:r.get(k,"") for k in fields})

def relationship_pairs(rows):
    pairs={}
    for r in rows:
        st=clean(r.get("status")).upper()
        if st in {"REJECTED","CONTRADICTED","SUPERSEDED"}: continue
        a=clean(r.get("source_id")); b=clean(r.get("target_id"))
        if not a or not b or a==b: continue
        key=tuple(sorted((a,b)))
        pairs.setdefault(key,[]).append(r)
    return pairs

def stance_index(rows):
    idx=defaultdict(lambda:defaultdict(list))
    pair_types=defaultdict(set)
    for r in rows:
        src=clean(r.get("source_entity_id"))
        tgt=clean(r.get("target_entity_id"))
        typ=clean(r.get("stance_type")).upper()
        adoption=clean(r.get("speaker_adoption")).upper()
        if not src or not tgt or not typ: continue
        if adoption and adoption not in {"ADOPTS","SUPPORTS","OWN_STATEMENT",""}: continue
        idx[tgt][src].append(r)
        pair_types[(src,tgt)].add(typ)
    return idx,pair_types

def current_memberships(rows):
    if not rows:return {},{}
    sids=sorted({r.get("snapshot_id","") for r in rows if r.get("snapshot_id")})
    if not sids:return {},{}
    sid=sids[-1]
    primary={}
    metrics={}
    for r in rows:
        if r.get("snapshot_id")!=sid: continue
        n=r.get("node_id","")
        if str(r.get("primary_membership","")).lower()=="true":
            primary[n]=r.get("community_id","")
        metrics[n]=r
    return primary,metrics

def signal_strength(rel_count, stance_a, stance_b, contents_a, contents_b):
    raw=1.5*math.log1p(rel_count)+math.log1p(stance_a)+math.log1p(stance_b)+0.5*math.log1p(contents_a+contents_b)
    return round(min(100.0,raw*12.0),2)

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--connections",default="data/connections.csv")
    ap.add_argument("--stances",default="data/analysis/stance_events.csv")
    ap.add_argument("--memberships",default="data/graph/community_memberships.csv")
    ap.add_argument("--output",default="data/graph/motif_candidates.csv")
    args=ap.parse_args()

    repo=Path(__file__).resolve().parents[1]
    rel=relationship_pairs(read_csv(repo/args.connections))
    stances,pair_types=stance_index(read_csv(repo/args.stances))
    primary,metrics=current_memberships(read_csv(repo/args.memberships))
    detected=now()
    motifs=[]

    # Connected associates who independently take the same positive/negative stance toward a third target.
    for target,by_source in stances.items():
        sources=sorted(by_source)
        for i,a in enumerate(sources):
            for b in sources[i+1:]:
                key=tuple(sorted((a,b)))
                if key not in rel: continue
                atypes={clean(x.get("stance_type")).upper() for x in by_source[a]}
                btypes={clean(x.get("stance_type")).upper() for x in by_source[b]}
                polarity=""
                if atypes & NEGATIVE and btypes & NEGATIVE: polarity="NEGATIVE"
                elif atypes & POSITIVE and btypes & POSITIVE: polarity="POSITIVE"
                if not polarity: continue
                ca=len({x.get("content_id","") for x in by_source[a] if x.get("content_id")})
                cb=len({x.get("content_id","") for x in by_source[b] if x.get("content_id")})
                strength=signal_strength(len(rel[key]),len(by_source[a]),len(by_source[b]),ca,cb)
                typ="SHARED_ADVERSARY_CONNECTED" if polarity=="NEGATIVE" else "SHARED_SUPPORT_CONNECTED"
                source_ids=[]
                for rr in rel[key]:
                    source_ids.extend([x for x in clean(rr.get("source_ids")).split(";") if x])
                motifs.append({
                    "motif_id":mid("MF_",typ,a,b,target),"motif_type":typ,"detected_at":detected,
                    "window_start":"","window_end":"",
                    "node_ids":json.dumps([a,b,target],ensure_ascii=False),
                    "claim_ids":"[]",
                    "edge_event_ids":json.dumps(
                        [x.get("stance_event_id","") for x in by_source[a]+by_source[b] if x.get("stance_event_id")],
                        ensure_ascii=False
                    ),
                    "source_ids":json.dumps(sorted(set(source_ids)),ensure_ascii=False),
                    "signal_strength":strength,"baseline_rate":"","observed_rate":"","lift":"",
                    "status":"OPEN","review_notes":
                        "Investigative signal only. Shared stance among documented associates does not establish coordination."
                })

    # Same source-target pair has materially opposed stance types over time.
    for (src,tgt),types in pair_types.items():
        if types & NEGATIVE and types & POSITIVE:
            motifs.append({
                "motif_id":mid("MF_","STANCE_REVERSAL",src,tgt),"motif_type":"STANCE_REVERSAL",
                "detected_at":detected,"window_start":"","window_end":"",
                "node_ids":json.dumps([src,tgt],ensure_ascii=False),"claim_ids":"[]","edge_event_ids":"[]","source_ids":"[]",
                "signal_strength":35.0,"baseline_rate":"","observed_rate":"","lift":"",
                "status":"OPEN","review_notes":
                    "Check chronology/topic before concluding a genuine reversal; stance may differ by issue."
            })

    # Structural bridges across primary relationship communities.
    for node,r in metrics.items():
        try:
            p=float(r.get("participation_coefficient") or 0)
            bridge=float(r.get("bridge_score") or 0)
            brokerage=float(r.get("brokerage_score") or 0)
        except Exception:
            continue
        if p>=0.55 and (bridge>=0.75 or brokerage>=0.03):
            motifs.append({
                "motif_id":mid("MF_","CROSS_COMMUNITY_BRIDGE",node,r.get("snapshot_id","")),
                "motif_type":"CROSS_COMMUNITY_BRIDGE","detected_at":detected,
                "window_start":"","window_end":"","node_ids":json.dumps([node],ensure_ascii=False),
                "claim_ids":"[]","edge_event_ids":"[]","source_ids":"[]",
                "signal_strength":round(min(100,25+45*p+15*min(1,bridge)),2),
                "baseline_rate":"","observed_rate":"","lift":"","status":"OPEN",
                "review_notes":
                    f"Structural bridge signal in relationship snapshot {r.get('snapshot_id','')}; not evidence of misconduct."
            })

    # Deduplicate by motif_id and preserve prior review state when possible.
    out=(repo/args.output).resolve()
    prior={r.get("motif_id",""):r for r in read_csv(out)}
    dedup={}
    for r in motifs:
        old=prior.get(r["motif_id"])
        if old:
            r["status"]=old.get("status") or r["status"]
            r["review_notes"]=old.get("review_notes") or r["review_notes"]
        dedup[r["motif_id"]]=r

    rows=sorted(dedup.values(),key=lambda r:(-float(r.get("signal_strength") or 0),r["motif_type"],r["motif_id"]))
    fields=[
        "motif_id","motif_type","detected_at","window_start","window_end","node_ids","claim_ids",
        "edge_event_ids","source_ids","signal_strength","baseline_rate","observed_rate","lift","status","review_notes"
    ]
    write_csv(out,rows,fields)
    print(json.dumps({
        "detected_at":detected,"motif_count":len(rows),
        "by_type":{t:sum(1 for r in rows if r["motif_type"]==t) for t in sorted({r["motif_type"] for r in rows})}
    },indent=2))
    return 0

if __name__=="__main__":
    raise SystemExit(main())
