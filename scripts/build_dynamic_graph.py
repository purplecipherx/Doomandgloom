#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import math
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import networkx as nx

RELATIONSHIP_WEIGHTS = {
    "OWNS": 10.0,
    "CONTROLS": 10.0,
    "FINANCIAL": 9.0,
    "PAYS": 9.0,
    "FUNDS": 9.0,
    "INVESTS_IN": 9.0,
    "EMPLOYS": 8.0,
    "OFFICER": 8.0,
    "DIRECTOR": 8.0,
    "BOARD_MEMBER_OF": 8.0,
    "FORMAL_PROFESSIONAL": 7.0,
    "CONTRACTS_WITH": 7.0,
    "JOINT_PRODUCT": 7.0,
    "SPONSORSHIP": 6.0,
    "AFFILIATE_REFERRAL": 6.0,
    "SELLS": 5.0,
    "MANUFACTURES": 5.0,
    "DISTRIBUTES": 5.0,
    "LICENSES": 5.0,
    "COMMERCIAL_PROMOTION": 4.0,
    "COAUTHORS": 4.0,
    "COPRODUCES": 4.0,
    "RECURRING_MEDIA": 3.0,
    "RECURRING_CONFERENCE": 2.5,
    "SINGLE_MEDIA": 1.0,
    "SINGLE_CONFERENCE": 0.8,
    "IDEOLOGICAL_TOPICAL": 0.0,
}

INCLUDE_STATUSES = {
    "", "ACTIVE", "VERIFIED", "SUPPORTED", "CONFIRMED", "DOCUMENTED", "SEED"
}
EXCLUDE_STATUSES = {"REJECTED", "CONTRADICTED", "SUPERSEDED"}

def now():
    return datetime.now(timezone.utc).isoformat()

def clean(s):
    return str(s or "").strip()

def fnum(s, default=0.0):
    try: return float(s)
    except Exception: return default

def read_csv(path: Path):
    if not path.exists():
        return []
    return list(csv.DictReader(path.open(encoding="utf-8-sig")))

def append_csv(path: Path, rows, fields, unique_key=None):
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = read_csv(path)
    if unique_key:
        old = {tuple(r.get(k,"") for k in unique_key):r for r in existing}
        for r in rows:
            old[tuple(str(r.get(k,"")) for k in unique_key)] = {k:r.get(k,"") for k in fields}
        rows = list(old.values())
    else:
        rows = existing + rows
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        w=csv.DictWriter(f,fieldnames=fields); w.writeheader()
        for r in rows: w.writerow({k:r.get(k,"") for k in fields})

def relation_weight(r):
    rel=clean(r.get("relationship_type")).upper()
    base=RELATIONSHIP_WEIGHTS.get(rel, 1.0)
    evidence=max(1.0,fnum(r.get("evidence_count"),1.0))
    primary=max(0.0,fnum(r.get("primary_source_count"),0.0))
    confidence=clean(r.get("confidence")).upper()
    conf_mult={"HIGH":1.0,"MEDIUM":0.8,"LOW":0.55,"VERIFIED":1.0}.get(confidence,0.85)
    evidence_mult=1.0 + min(1.5, math.log1p(evidence)/3.0) + min(0.5, primary*0.08)
    return base * conf_mult * evidence_mult

def build_graph(rows):
    g=nx.Graph()
    accepted=[]
    for r in rows:
        status=clean(r.get("status")).upper()
        if status in EXCLUDE_STATUSES or (status and status not in INCLUDE_STATUSES):
            continue
        a=clean(r.get("source_id")); b=clean(r.get("target_id"))
        if not a or not b or a==b:
            continue
        rel=clean(r.get("relationship_type")).upper()
        w=relation_weight(r)
        if w<=0:
            continue
        accepted.append(r)
        if g.has_edge(a,b):
            g[a][b]["weight"] += w
            g[a][b]["evidence_count"] += max(1,int(fnum(r.get("evidence_count"),1)))
            g[a][b]["relationship_types"].add(rel)
            if clean(r.get("edge_id")): g[a][b]["edge_ids"].add(clean(r.get("edge_id")))
        else:
            g.add_edge(
                a,b,weight=w,
                evidence_count=max(1,int(fnum(r.get("evidence_count"),1))),
                relationship_types={rel},
                edge_ids={clean(r.get("edge_id"))} if clean(r.get("edge_id")) else set()
            )
    return g, accepted

def louvain(g, seed=42, resolution=1.0):
    if g.number_of_nodes()==0:
        return []
    if g.number_of_edges()==0:
        return [{n} for n in g.nodes]
    return list(nx.community.louvain_communities(g, weight="weight", seed=seed, resolution=resolution))

def membership_strengths(g, communities):
    node_to_primary={}
    for i,c in enumerate(communities):
        for n in c: node_to_primary[n]=i

    rows=[]
    for n in g.nodes:
        by_comm=defaultdict(float)
        total=0.0
        for nbr,d in g[n].items():
            w=float(d.get("weight",1.0)); total+=w
            by_comm[node_to_primary[nbr]] += w
        primary=node_to_primary[n]
        if total<=0:
            strengths={primary:1.0}
        else:
            strengths={c:w/total for c,w in by_comm.items()}
            if primary not in strengths:
                strengths[primary]=0.0
        for c,s in strengths.items():
            rows.append((n,c,s,c==primary))
    return rows

def participation(g, node, node_to_primary):
    weights=defaultdict(float); total=0.0
    for nbr,d in g[node].items():
        w=float(d.get("weight",1.0)); total+=w; weights[node_to_primary[nbr]]+=w
    if total<=0: return 0.0
    return 1.0-sum((w/total)**2 for w in weights.values())

def latest_snapshot_memberships(path: Path, current_snapshot):
    rows=read_csv(path)
    ids=[]
    for r in rows:
        sid=r.get("snapshot_id","")
        if sid and sid!=current_snapshot: ids.append(sid)
    if not ids: return "",{}
    prev=sorted(set(ids))[-1]
    out=defaultdict(dict)
    for r in rows:
        if r.get("snapshot_id")!=prev: continue
        out[r.get("community_id","")][r.get("node_id","")]=fnum(r.get("membership_strength"),0)
    return prev,dict(out)

def weighted_jaccard(a,b):
    nodes=set(a)|set(b)
    if not nodes: return 0.0
    num=sum(min(a.get(n,0.0),b.get(n,0.0)) for n in nodes)
    den=sum(max(a.get(n,0.0),b.get(n,0.0)) for n in nodes)
    return num/den if den else 0.0

def lineage_rows(prev_sid,prev,new_sid,new,threshold=0.18):
    if not prev_sid:
        return [{
            "from_snapshot_id":"","from_community_id":"",
            "to_snapshot_id":new_sid,"to_community_id":cid,
            "lineage_type":"BIRTH","weighted_overlap":0,"jaccard_overlap":0,
            "shared_member_count":0,"notes":"No prior snapshot"
        } for cid in new]

    matches=[]
    for oc,om in prev.items():
        oset={n for n,v in om.items() if v>=0.15}
        for nc,nm in new.items():
            nset={n for n,v in nm.items() if v>=0.15}
            wj=weighted_jaccard(om,nm)
            union=oset|nset
            j=len(oset&nset)/len(union) if union else 0.0
            if max(wj,j)>=threshold:
                matches.append((oc,nc,wj,j,len(oset&nset)))
    old_to=defaultdict(list); new_from=defaultdict(list)
    for m in matches:
        old_to[m[0]].append(m); new_from[m[1]].append(m)

    out=[]
    for oc,nc,wj,j,shared in matches:
        if len(old_to[oc])>1 and len(new_from[nc])>1: typ="REFORMED"
        elif len(old_to[oc])>1: typ="SPLIT"
        elif len(new_from[nc])>1: typ="MERGE"
        else: typ="CONTINUE"
        out.append({
            "from_snapshot_id":prev_sid,"from_community_id":oc,
            "to_snapshot_id":new_sid,"to_community_id":nc,
            "lineage_type":typ,"weighted_overlap":round(wj,6),
            "jaccard_overlap":round(j,6),"shared_member_count":shared,"notes":""
        })
    matched_old={m[0] for m in matches}; matched_new={m[1] for m in matches}
    for oc in prev:
        if oc not in matched_old:
            out.append({
                "from_snapshot_id":prev_sid,"from_community_id":oc,
                "to_snapshot_id":new_sid,"to_community_id":"",
                "lineage_type":"DEATH","weighted_overlap":0,"jaccard_overlap":0,
                "shared_member_count":0,"notes":"No sufficient overlap with current communities"
            })
    for nc in new:
        if nc not in matched_new:
            out.append({
                "from_snapshot_id":prev_sid,"from_community_id":"",
                "to_snapshot_id":new_sid,"to_community_id":nc,
                "lineage_type":"BIRTH","weighted_overlap":0,"jaccard_overlap":0,
                "shared_member_count":0,"notes":"No sufficient overlap with previous communities"
            })
    return out

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--connections",default="data/connections.csv")
    ap.add_argument("--entities",default="data/entities.csv")
    ap.add_argument("--output-dir",default="data/graph")
    ap.add_argument("--snapshot-id",default="")
    ap.add_argument("--resolution",type=float,default=1.0)
    ap.add_argument("--seed",type=int,default=42)
    args=ap.parse_args()

    repo=Path(__file__).resolve().parents[1]
    connections=(repo/args.connections).resolve()
    entities=(repo/args.entities).resolve()
    out=(repo/args.output_dir).resolve()
    out.mkdir(parents=True,exist_ok=True)

    sid=args.snapshot_id or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    conn_rows=read_csv(connections)
    entity_rows=read_csv(entities)
    names={r.get("id",""):r.get("name","") for r in entity_rows}

    g,accepted=build_graph(conn_rows)
    communities=louvain(g,args.seed,args.resolution)
    communities=sorted(communities,key=lambda c:(-len(c),sorted(c)[0] if c else ""))

    node_to_primary={}
    comm_ids={}
    for i,c in enumerate(communities,1):
        cid=f"C_{sid}_{i:04d}"; comm_ids[i-1]=cid
        for n in c: node_to_primary[n]=i-1

    try:
        btw=nx.betweenness_centrality(g,weight="weight",normalized=True) if g.number_of_nodes() else {}
    except Exception:
        btw={n:0.0 for n in g}
    pr=nx.pagerank(g,weight="weight") if g.number_of_nodes() and g.number_of_edges() else {n:1/max(1,g.number_of_nodes()) for n in g}

    raw_members=membership_strengths(g,communities)
    member_rows=[]
    strength_by_node=defaultdict(dict)
    for n,c,s,is_primary in raw_members: strength_by_node[n][c]=s
    for n,c,s,is_primary in raw_members:
        p=participation(g,n,node_to_primary)
        wd=sum(float(d.get("weight",1.0)) for _,d in g[n].items())
        bridge=p*math.log1p(max(0.0,wd))
        brokerage=float(btw.get(n,0.0))
        outlier=1.0-max(strength_by_node[n].values() or [0.0])
        member_rows.append({
            "snapshot_id":sid,"node_id":n,"community_id":comm_ids[c],
            "membership_strength":round(s,6),"primary_membership":"true" if is_primary else "false",
            "within_community_strength":round(
                sum(float(d.get("weight",1.0)) for nbr,d in g[n].items() if node_to_primary.get(nbr)==c),6
            ),
            "participation_coefficient":round(p,6),"bridge_score":round(bridge,6),
            "brokerage_score":round(brokerage,6),"outlier_score":round(outlier,6),
            "evidence_edge_count":sum(int(d.get("evidence_count",1)) for _,d in g[n].items()),
            "notes":""
        })

    metric_rows=[]
    for n in g.nodes:
        p=participation(g,n,node_to_primary)
        wd=sum(float(d.get("weight",1.0)) for _,d in g[n].items())
        bridge=p*math.log1p(max(0.0,wd))
        metric_rows.append({
            "snapshot_id":sid,"node_id":n,"layer":"relationship",
            "degree":g.degree(n),"weighted_degree":round(wd,6),
            "betweenness":round(float(btw.get(n,0.0)),8),
            "pagerank":round(float(pr.get(n,0.0)),8),
            "participation_coefficient":round(p,6),
            "bridge_score":round(bridge,6),
            "brokerage_score":round(float(btw.get(n,0.0)),8),
            "outlier_score":round(1.0-max(strength_by_node[n].values() or [0.0]),6),
            "evidence_coverage":sum(int(d.get("evidence_count",1)) for _,d in g[n].items()),
            "notes":""
        })

    prev_sid,prev=latest_snapshot_memberships(out/"community_memberships.csv",sid)
    new=defaultdict(dict)
    for r in member_rows:
        new[r["community_id"]][r["node_id"]]=fnum(r["membership_strength"])
    lineage=lineage_rows(prev_sid,prev,sid,dict(new))

    snapshot_row={
        "snapshot_id":sid,"computed_at":now(),"window_start":"","window_end":"",
        "algorithm":"networkx_louvain+soft_neighbor_membership",
        "algorithm_version":getattr(nx,"__version__",""),
        "edge_policy":"documented relationship edges only; stance/shared-target excluded",
        "node_count":g.number_of_nodes(),"edge_count":g.number_of_edges(),
        "community_count":len(communities),
        "modularity":round(nx.community.modularity(g,communities,weight="weight"),8) if g.number_of_edges() and communities else 0,
        "notes":f"accepted_relationship_rows={len(accepted)} resolution={args.resolution} seed={args.seed}"
    }

    append_csv(out/"community_snapshots.csv",[snapshot_row],[
        "snapshot_id","computed_at","window_start","window_end","algorithm","algorithm_version",
        "edge_policy","node_count","edge_count","community_count","modularity","notes"
    ],["snapshot_id"])
    append_csv(out/"community_memberships.csv",member_rows,[
        "snapshot_id","node_id","community_id","membership_strength","primary_membership",
        "within_community_strength","participation_coefficient","bridge_score","brokerage_score",
        "outlier_score","evidence_edge_count","notes"
    ],["snapshot_id","node_id","community_id"])
    append_csv(out/"node_metrics.csv",metric_rows,[
        "snapshot_id","node_id","layer","degree","weighted_degree","betweenness","pagerank",
        "participation_coefficient","bridge_score","brokerage_score","outlier_score","evidence_coverage","notes"
    ],["snapshot_id","node_id","layer"])
    append_csv(out/"community_lineage.csv",lineage,[
        "from_snapshot_id","from_community_id","to_snapshot_id","to_community_id","lineage_type",
        "weighted_overlap","jaccard_overlap","shared_member_count","notes"
    ],["from_snapshot_id","from_community_id","to_snapshot_id","to_community_id"])

    snapdir=out/"snapshots"; snapdir.mkdir(exist_ok=True)
    payload={
        "snapshot":snapshot_row,
        "communities":[
            {"community_id":comm_ids[i],"size":len(c),"members":[{"id":n,"name":names.get(n,n)} for n in sorted(c)]}
            for i,c in enumerate(communities)
        ],
        "nodes":[
            {"id":n,"name":names.get(n,n),"primary_community":comm_ids.get(node_to_primary.get(n),""),
             "metrics":next((m for m in metric_rows if m["node_id"]==n),{})}
            for n in g.nodes
        ],
        "edges":[
            {"source":a,"target":b,"weight":round(float(d.get("weight",1.0)),6),
             "relationship_types":sorted(d.get("relationship_types",set())),
             "evidence_count":int(d.get("evidence_count",1)),"edge_ids":sorted(d.get("edge_ids",set()))}
            for a,b,d in g.edges(data=True)
        ],
        "lineage":lineage
    }
    (snapdir/f"{sid}.json").write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding="utf-8")

    print(json.dumps(snapshot_row,indent=2))
    print(f"Snapshot: {snapdir/f'{sid}.json'}")
    return 0

if __name__=="__main__":
    raise SystemExit(main())
