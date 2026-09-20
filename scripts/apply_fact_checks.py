#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
from datetime import datetime, timezone
from pathlib import Path

ALLOWED={
    "VERIFIED","SUPPORTED_INFERENCE","DISPUTED","UNVERIFIED","CONTRADICTED",
    "OPINION_OR_NOT_CHECKABLE","NOT_APPLICABLE"
}
CHECKABLE={"CHECKABLE","PARTLY_CHECKABLE"}

def now():
    return datetime.now(timezone.utc).isoformat()

def load_jsonl_map(path:Path,key):
    out={}
    if path.exists():
        for line in path.read_text(encoding="utf-8",errors="replace").splitlines():
            if not line.strip(): continue
            try:
                r=json.loads(line)
                if r.get(key): out[r[key]]=r
            except Exception: pass
    return out

def write_jsonl(path:Path,rows):
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open("w",encoding="utf-8") as f:
        for r in rows: f.write(json.dumps(r,ensure_ascii=False)+"\n")

def write_csv(path:Path,rows,fields):
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open("w",newline="",encoding="utf-8-sig") as f:
        w=csv.DictWriter(f,fieldnames=fields); w.writeheader()
        for r in rows: w.writerow({k:r.get(k,"") for k in fields})

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("fact_check_jsonl")
    ap.add_argument("--analysis-dir",default="data/analysis")
    ap.add_argument("--reviewer",default="")
    args=ap.parse_args()

    ad=Path(args.analysis_dir).resolve()
    claims_path=ad/"atomic_claims.csv"
    claims=list(csv.DictReader(claims_path.open(encoding="utf-8-sig")))
    claim_map={r["claim_id"]:r for r in claims}
    checks_path=ad/"fact_checks.jsonl"
    checks=load_jsonl_map(checks_path,"claim_id")

    accepted=0
    for line in Path(args.fact_check_jsonl).resolve().read_text(encoding="utf-8",errors="replace").splitlines():
        if not line.strip(): continue
        r=json.loads(line)
        cid=r.get("claim_id")
        if cid not in claim_map:
            raise SystemExit(f"Unknown claim_id: {cid}")
        status=(r.get("status") or "").upper()
        if status not in ALLOWED:
            raise SystemExit(f"Invalid status for {cid}: {status}")
        r["claim_id"]=cid
        r["status"]=status
        r["reviewer"]=r.get("reviewer") or args.reviewer
        r["reviewed_at"]=r.get("reviewed_at") or now()
        r.setdefault("primary_sources",[])
        r.setdefault("independent_sources",[])
        r.setdefault("contradicting_sources",[])
        r.setdefault("subject_response_sources",[])
        r.setdefault("reasoning_summary","")
        r.setdefault("limitations","")
        checks[cid]=r; accepted+=1

    ordered=[checks[k] for k in sorted(checks)]
    write_jsonl(checks_path,ordered)

    check_fields=[
        "claim_id","status","reviewer","reviewed_at","reasoning_summary","limitations",
        "primary_sources_json","independent_sources_json","contradicting_sources_json","subject_response_sources_json"
    ]
    check_rows=[]
    for r in ordered:
        check_rows.append({
            "claim_id":r["claim_id"],"status":r["status"],"reviewer":r.get("reviewer",""),
            "reviewed_at":r.get("reviewed_at",""),"reasoning_summary":r.get("reasoning_summary",""),
            "limitations":r.get("limitations",""),
            "primary_sources_json":json.dumps(r.get("primary_sources") or [],ensure_ascii=False),
            "independent_sources_json":json.dumps(r.get("independent_sources") or [],ensure_ascii=False),
            "contradicting_sources_json":json.dumps(r.get("contradicting_sources") or [],ensure_ascii=False),
            "subject_response_sources_json":json.dumps(r.get("subject_response_sources") or [],ensure_ascii=False),
        })
    write_csv(ad/"fact_checks.csv",check_rows,check_fields)

    for c in claims:
        c["fact_check_status"]=checks.get(c["claim_id"],{}).get("status") or c.get("fact_check_status") or "PENDING"

    claim_fields=list(claims[0].keys()) if claims else []
    write_csv(claims_path,claims,claim_fields)

    unresolved=[c for c in claims if c.get("checkability") in CHECKABLE and c.get("fact_check_status") not in ALLOWED]
    queue_fields=[
        "claim_id","unit_id","content_id","start_seconds","end_seconds","speaker_id","claim_text","claim_type",
        "checkability","severity","target_entity_ids","source_path"
    ]
    write_csv(ad/"fact_check_queue.csv",unresolved,queue_fields)

    ledger_path=ad/"transcript_units.csv"
    units=list(csv.DictReader(ledger_path.open(encoding="utf-8-sig")))
    by_unit={}
    for c in claims:
        if c.get("checkability") in CHECKABLE:
            by_unit.setdefault(c["unit_id"],[]).append(c)

    for u in units:
        if u.get("semantic_review_status")!="COMPLETE":
            continue
        cs=by_unit.get(u["unit_id"],[])
        if not cs:
            u["fact_check_status"]="NOT_APPLICABLE"
        elif all((c.get("fact_check_status") or "") in ALLOWED for c in cs):
            u["fact_check_status"]="COMPLETE"
        else:
            u["fact_check_status"]="PENDING"
    unit_fields=list(units[0].keys()) if units else []
    write_csv(ledger_path,units,unit_fields)

    print(json.dumps({
        "accepted_fact_checks":accepted,
        "total_fact_checks":len(checks),
        "remaining_fact_checks":len(unresolved)
    },indent=2))
    return 0

if __name__=="__main__":
    raise SystemExit(main())
