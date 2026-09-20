#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path

CHECKABLE = {"CHECKABLE","PARTLY_CHECKABLE"}

def now():
    return datetime.now(timezone.utc).isoformat()

def norm(s):
    return re.sub(r"\s+"," ",str(s or "")).strip()

def sid(prefix,*parts):
    raw="\x1f".join(norm(x).lower() for x in parts)
    return prefix + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24].upper()

def load_jsonl_map(path: Path,key):
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
    ap.add_argument("review_jsonl")
    ap.add_argument("--analysis-dir",default="data/analysis")
    ap.add_argument("--reviewer",default="")
    args=ap.parse_args()

    ad=Path(args.analysis_dir).resolve()
    ledger_path=ad/"transcript_units.csv"
    units=list(csv.DictReader(ledger_path.open(encoding="utf-8-sig")))
    unit_map={r["unit_id"]:r for r in units}

    reviews_path=ad/"semantic_reviews.jsonl"
    reviews=load_jsonl_map(reviews_path,"unit_id")
    incoming=Path(args.review_jsonl).resolve()

    accepted=0
    for line in incoming.read_text(encoding="utf-8",errors="replace").splitlines():
        if not line.strip(): continue
        r=json.loads(line)
        uid=r.get("unit_id")
        if uid not in unit_map:
            raise SystemExit(f"Unknown unit_id in review: {uid}")
        r["unit_id"]=uid
        r["reviewed_at"]=r.get("reviewed_at") or now()
        r["reviewer"]=r.get("reviewer") or args.reviewer
        r.setdefault("speech_act",[])
        r.setdefault("mentions",[])
        r.setdefault("atomic_claims",[])
        r.setdefault("relationships",[])
        r.setdefault("stances",[])
        r.setdefault("products",[])
        r.setdefault("predictions",[])
        r.setdefault("money_or_conflict_signals",[])
        r.setdefault("citations_or_sources_mentioned",[])
        r.setdefault("notes","")
        reviews[uid]=r; accepted+=1

    ordered=[reviews[k] for k in sorted(reviews)]
    write_jsonl(reviews_path,ordered)

    fact_checks=load_jsonl_map(ad/"fact_checks.jsonl","claim_id")
    claims=[]; mentions=[]; relationships=[]; stances=[]; products=[]; predictions=[]; money=[]; citations=[]

    for uid,r in reviews.items():
        u=unit_map[uid]
        for m in r.get("mentions") or []:
            surface=norm(m.get("surface") or m.get("text"))
            if not surface: continue
            mentions.append({
                "mention_id":m.get("mention_id") or sid("MN_",uid,surface,m.get("entity_type","")),
                "unit_id":uid,"content_id":u["content_id"],"start_seconds":u["start_seconds"],"end_seconds":u["end_seconds"],
                "speaker_id":u["speaker_id"],"surface":surface,"entity_type":m.get("entity_type",""),
                "canonical_entity_id":m.get("canonical_entity_id",""),"confidence":m.get("confidence",""),
                "source_path":u["source_path"]
            })

        for c in r.get("atomic_claims") or []:
            text=norm(c.get("claim_text"))
            if not text: continue
            cid=c.get("claim_id") or sid("CL_",uid,text)
            checkability=(c.get("checkability") or "CHECKABLE").upper()
            fc=fact_checks.get(cid,{})
            status=fc.get("status") or ("NOT_APPLICABLE" if checkability not in CHECKABLE else "PENDING")
            claims.append({
                "claim_id":cid,"unit_id":uid,"content_id":u["content_id"],"start_seconds":u["start_seconds"],"end_seconds":u["end_seconds"],
                "speaker_id":u["speaker_id"],"claim_text":text,"claim_type":c.get("claim_type","other"),
                "checkability":checkability,"severity":(c.get("severity") or "LOW").upper(),
                "target_entity_ids":json.dumps(c.get("target_entity_ids") or [],ensure_ascii=False),
                "claimant_entity_id":c.get("claimant_entity_id",""),"attribution_mode":c.get("attribution_mode",""),
                "requires_primary_source":bool(c.get("requires_primary_source",False)),
                "fact_check_status":status,"source_path":u["source_path"]
            })

        for rel in r.get("relationships") or []:
            desc=norm(rel.get("description") or rel.get("relationship_text"))
            relationships.append({
                "relationship_claim_id":rel.get("relationship_claim_id") or sid("RL_",uid,desc,json.dumps(rel,sort_keys=True)),
                "unit_id":uid,"content_id":u["content_id"],"speaker_id":u["speaker_id"],
                "subject_entity_id":rel.get("subject_entity_id",""),"object_entity_id":rel.get("object_entity_id",""),
                "relationship_type":rel.get("relationship_type",""),"description":desc,
                "confidence":rel.get("confidence",""),"source_path":u["source_path"]
            })

        for st in r.get("stances") or []:
            target_entity_id=st.get("target_entity_id","")
            target_claim_id=st.get("target_claim_id","")
            stance_type=(st.get("stance_type") or "").upper()
            topic=norm(st.get("topic") or "")
            excerpt=norm(st.get("excerpt") or st.get("text") or "")
            if not stance_type or not (target_entity_id or target_claim_id):
                continue
            stances.append({
                "stance_event_id":st.get("stance_event_id") or sid(
                    "ST_",uid,target_entity_id,target_claim_id,stance_type,topic,excerpt
                ),
                "unit_id":uid,"content_id":u["content_id"],"start_seconds":u["start_seconds"],
                "end_seconds":u["end_seconds"],"speaker_id":u["speaker_id"],
                "source_entity_id":st.get("source_entity_id") or r.get("speaker_entity_id",""),
                "target_entity_id":target_entity_id,"target_claim_id":target_claim_id,
                "stance_type":stance_type,"topic":topic,"excerpt":excerpt,
                "speaker_adoption":(st.get("speaker_adoption") or "ADOPTS").upper(),
                "explicitness":(st.get("explicitness") or "EXPLICIT").upper(),
                "confidence":st.get("confidence",""),"source_path":u["source_path"]
            })

        for p in r.get("products") or []:
            name=norm(p.get("name") or p.get("product_name"))
            products.append({
                "product_mention_id":p.get("product_mention_id") or sid("PM_",uid,name,json.dumps(p,sort_keys=True)),
                "unit_id":uid,"content_id":u["content_id"],"speaker_id":u["speaker_id"],"name":name,
                "product_id":p.get("product_id",""),"role":p.get("role",""),"price":p.get("price",""),
                "cta":p.get("cta",""),"sponsor":p.get("sponsor",""),"affiliate_or_promo":p.get("affiliate_or_promo",""),
                "source_path":u["source_path"]
            })

        for p in r.get("predictions") or []:
            text=norm(p.get("prediction_text") or p.get("text"))
            predictions.append({
                "prediction_id":p.get("prediction_id") or sid("PD_",uid,text),
                "unit_id":uid,"content_id":u["content_id"],"speaker_id":u["speaker_id"],
                "prediction_text":text,"target_date":p.get("target_date",""),"conditions":p.get("conditions",""),
                "measurable_outcome":p.get("measurable_outcome",""),"status":p.get("status","PENDING"),
                "source_path":u["source_path"]
            })

        for m in r.get("money_or_conflict_signals") or []:
            text=norm(m.get("description") or m.get("text"))
            money.append({
                "signal_id":m.get("signal_id") or sid("MC_",uid,text,json.dumps(m,sort_keys=True)),
                "unit_id":uid,"content_id":u["content_id"],"speaker_id":u["speaker_id"],
                "signal_type":m.get("signal_type",""),"entity_ids":json.dumps(m.get("entity_ids") or [],ensure_ascii=False),
                "description":text,"amount":m.get("amount",""),"disclosure_status":m.get("disclosure_status",""),
                "source_path":u["source_path"]
            })

        for c in r.get("citations_or_sources_mentioned") or []:
            text=norm(c.get("name") or c.get("citation_text") or c.get("source"))
            citations.append({
                "citation_mention_id":c.get("citation_mention_id") or sid("CS_",uid,text,json.dumps(c,sort_keys=True)),
                "unit_id":uid,"content_id":u["content_id"],"speaker_id":u["speaker_id"],
                "citation_text":text,"url":c.get("url",""),"claimed_support":c.get("claimed_support",""),
                "source_path":u["source_path"]
            })

    write_csv(ad/"atomic_claims.csv",claims,[
        "claim_id","unit_id","content_id","start_seconds","end_seconds","speaker_id","claim_text","claim_type",
        "checkability","severity","target_entity_ids","claimant_entity_id","attribution_mode","requires_primary_source",
        "fact_check_status","source_path"
    ])
    write_csv(ad/"mentions.csv",mentions,[
        "mention_id","unit_id","content_id","start_seconds","end_seconds","speaker_id","surface","entity_type",
        "canonical_entity_id","confidence","source_path"
    ])
    write_csv(ad/"relationship_claims.csv",relationships,[
        "relationship_claim_id","unit_id","content_id","speaker_id","subject_entity_id","object_entity_id",
        "relationship_type","description","confidence","source_path"
    ])
    write_csv(ad/"stance_events.csv",stances,[
        "stance_event_id","unit_id","content_id","start_seconds","end_seconds","speaker_id",
        "source_entity_id","target_entity_id","target_claim_id","stance_type","topic","excerpt",
        "speaker_adoption","explicitness","confidence","source_path"
    ])
    write_csv(ad/"product_mentions.csv",products,[
        "product_mention_id","unit_id","content_id","speaker_id","name","product_id","role","price","cta","sponsor",
        "affiliate_or_promo","source_path"
    ])
    write_csv(ad/"predictions.csv",predictions,[
        "prediction_id","unit_id","content_id","speaker_id","prediction_text","target_date","conditions",
        "measurable_outcome","status","source_path"
    ])
    write_csv(ad/"money_conflict_signals.csv",money,[
        "signal_id","unit_id","content_id","speaker_id","signal_type","entity_ids","description","amount",
        "disclosure_status","source_path"
    ])
    write_csv(ad/"cited_sources.csv",citations,[
        "citation_mention_id","unit_id","content_id","speaker_id","citation_text","url","claimed_support","source_path"
    ])

    unresolved=[c for c in claims if c["checkability"] in CHECKABLE and c["fact_check_status"] not in {
        "VERIFIED","SUPPORTED_INFERENCE","DISPUTED","UNVERIFIED","CONTRADICTED","OPINION_OR_NOT_CHECKABLE","NOT_APPLICABLE"
    }]
    write_csv(ad/"fact_check_queue.csv",unresolved,[
        "claim_id","unit_id","content_id","start_seconds","end_seconds","speaker_id","claim_text","claim_type",
        "checkability","severity","target_entity_ids","source_path"
    ])

    claims_by_unit={}
    for c in claims: claims_by_unit.setdefault(c["unit_id"],[]).append(c)
    for u in units:
        if u["unit_id"] in reviews:
            u["semantic_review_status"]="COMPLETE"
            cs=[c for c in claims_by_unit.get(u["unit_id"],[]) if c["checkability"] in CHECKABLE]
            if not cs:
                u["fact_check_status"]="NOT_APPLICABLE"
            elif all(c["fact_check_status"]!="PENDING" for c in cs):
                u["fact_check_status"]="COMPLETE"
            else:
                u["fact_check_status"]="PENDING"
    fields=list(units[0].keys()) if units else []
    write_csv(ledger_path,units,fields)

    idx_path=ad/"review_batches"/"review_batch_index.csv"
    if idx_path.exists():
        idx=list(csv.DictReader(idx_path.open(encoding="utf-8-sig")))
        for row in idx:
            if row["unit_id"] in reviews: row["status"]="COMPLETE"
        write_csv(idx_path,idx,["unit_id","batch_id","batch_path","created_at","status"])

    print(json.dumps({
        "accepted_reviews":accepted,"total_reviews":len(reviews),"claims":len(claims),
        "fact_checks_pending":len(unresolved),"mentions":len(mentions),"relationships":len(relationships),
        "stances":len(stances),"products":len(products),"predictions":len(predictions),"money_conflict_signals":len(money)
    },indent=2))
    return 0

if __name__=="__main__":
    raise SystemExit(main())
