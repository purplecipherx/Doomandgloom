#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import subprocess
import sys
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
    ap.add_argument("--skip-voice-identity-sync",action="store_true")
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
        r.setdefault("semantic_events",[])
        r.setdefault("mentions",[])
        r.setdefault("atomic_claims",[])
        r.setdefault("relationships",[])
        r.setdefault("stances",[])
        r.setdefault("speaker_identity_clues",[])
        r.setdefault("products",[])
        r.setdefault("predictions",[])
        r.setdefault("money_or_conflict_signals",[])
        r.setdefault("citations_or_sources_mentioned",[])
        r.setdefault("notes","")
        reviews[uid]=r; accepted+=1

    ordered=[reviews[k] for k in sorted(reviews)]
    write_jsonl(reviews_path,ordered)

    fact_checks=load_jsonl_map(ad/"fact_checks.jsonl","claim_id")
    semantic_events=[]; claims=[]; mentions=[]; relationships=[]; stances=[]; identity_clues=[]; products=[]; predictions=[]; money=[]; citations=[]

    for uid,r in reviews.items():
        u=unit_map[uid]
        for m in r.get("mentions") or []:
            surface=norm(m.get("surface") or m.get("text"))
            if not surface: continue
            mentions.append({
                "mention_id":m.get("mention_id") or sid("MN_",uid,surface,m.get("entity_type","")),
                "unit_id":uid,"content_id":u["content_id"],"start_seconds":u["start_seconds"],"end_seconds":u["end_seconds"],
                "speaker_id":u["speaker_id"],"surface":surface,
                "normalized_surface":norm(m.get("normalized_surface") or surface),
                "entity_type":m.get("entity_type",""),
                "canonical_entity_id":m.get("canonical_entity_id",""),
                "resolution_status":(m.get("resolution_status") or ("RESOLVED" if m.get("canonical_entity_id") else "UNRESOLVED")).upper(),
                "reference_mode":(m.get("reference_mode") or "EXPLICIT").upper(),
                "transcript_fragmented":bool(m.get("transcript_fragmented",False)),
                "correction_candidate":norm(m.get("correction_candidate") or ""),
                "confidence":m.get("confidence",""),
                "source_path":u["source_path"]
            })

        for ev in r.get("semantic_events") or []:
            predicate=(ev.get("predicate_code") or "").upper()
            raw_predicate=norm(ev.get("raw_predicate") or ev.get("predicate_phrase") or "")
            if not predicate:
                continue
            source_entity_id=ev.get("source_entity_id") or r.get("speaker_entity_id","") or u.get("resolved_entity_id","")
            target_entity_id=ev.get("target_entity_id","")
            target_surface=norm(ev.get("target_surface") or "")
            target_claim_id=ev.get("target_claim_id","")
            object_entity_id=ev.get("object_entity_id","")
            object_surface=norm(ev.get("object_surface") or "")
            semantic_events.append({
                "semantic_event_id":ev.get("semantic_event_id") or sid(
                    "SE_",uid,predicate,source_entity_id,target_entity_id,target_surface,target_claim_id,
                    object_entity_id,object_surface,raw_predicate,ev.get("topic","")
                ),
                "unit_id":uid,"content_id":u["content_id"],
                "start_seconds":u.get("start_seconds",""),"end_seconds":u.get("end_seconds",""),
                "speaker_id":u.get("speaker_id",""),"canonical_voice_id":u.get("canonical_voice_id",""),
                "source_entity_id":source_entity_id,"source_surface":norm(ev.get("source_surface") or ""),
                "predicate_code":predicate,"predicate_family":(ev.get("predicate_family") or "").upper(),
                "raw_predicate":raw_predicate,
                "target_entity_id":target_entity_id,"target_surface":target_surface,"target_claim_id":target_claim_id,
                "object_entity_id":object_entity_id,"object_surface":object_surface,
                "topic":norm(ev.get("topic") or ""),
                "polarity":(ev.get("polarity") or "NOT_APPLICABLE").upper(),
                "speaker_adoption":(ev.get("speaker_adoption") or "ADOPTS").upper(),
                "attribution_mode":(ev.get("attribution_mode") or "OWN_CLAIM").upper(),
                "certainty":(ev.get("certainty") or "ASSERTED").upper(),
                "explicitness":(ev.get("explicitness") or "EXPLICIT").upper(),
                "negated":bool(ev.get("negated",False)),
                "conditional":bool(ev.get("conditional",False)),
                "hypothetical":bool(ev.get("hypothetical",False)),
                "commerciality":(ev.get("commerciality") or "NONE").upper(),
                "relationship_evidence_state":(ev.get("relationship_evidence_state") or "NONE").upper(),
                "fact_check_need":(ev.get("fact_check_need") or "NONE").upper(),
                "severity":(ev.get("severity") or "LOW").upper(),
                "source_span_text":norm(ev.get("source_span_text") or u.get("text","")),
                "confidence":ev.get("confidence",""),
                "notes":norm(ev.get("notes") or ""),
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

        for clue in r.get("speaker_identity_clues") or []:
            target_cluster=clue.get("target_acoustic_cluster_id") or u.get("acoustic_cluster_id","")
            target_raw=clue.get("target_raw_speaker_id") or u.get("raw_speaker_id","") or u.get("speaker_id","")
            claimed_entity_id=clue.get("claimed_entity_id","")
            claimed_name=norm(clue.get("claimed_name") or "")
            evidence_type=(clue.get("evidence_type") or "").upper()
            evidence_text=norm(clue.get("evidence_text") or clue.get("text") or "")
            if not (target_cluster or target_raw):
                continue
            if not (claimed_entity_id or claimed_name):
                continue
            identity_clues.append({
                "identity_clue_id":clue.get("identity_clue_id") or sid(
                    "IC_",uid,target_cluster,target_raw,claimed_entity_id,claimed_name,evidence_type,evidence_text
                ),
                "unit_id":uid,
                "content_id":u["content_id"],
                "channel_id":u.get("channel_id",""),
                "start_seconds":u.get("start_seconds",""),
                "end_seconds":u.get("end_seconds",""),
                "target_acoustic_cluster_id":target_cluster,
                "target_raw_speaker_id":target_raw,
                "current_canonical_voice_id":u.get("canonical_voice_id",""),
                "current_resolved_entity_id":u.get("resolved_entity_id",""),
                "claimed_entity_id":claimed_entity_id,
                "claimed_name":claimed_name,
                "evidence_type":evidence_type,
                "evidence_text":evidence_text,
                "confidence":clue.get("confidence",""),
                "speaker_adoption":(clue.get("speaker_adoption") or "ADOPTS").upper(),
                "source_path":u["source_path"],
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

    write_csv(ad/"semantic_events.csv",semantic_events,[
        "semantic_event_id","unit_id","content_id","start_seconds","end_seconds","speaker_id","canonical_voice_id",
        "source_entity_id","source_surface","predicate_code","predicate_family","raw_predicate",
        "target_entity_id","target_surface","target_claim_id","object_entity_id","object_surface","topic",
        "polarity","speaker_adoption","attribution_mode","certainty","explicitness","negated","conditional",
        "hypothetical","commerciality","relationship_evidence_state","fact_check_need","severity",
        "source_span_text","confidence","notes","source_path"
    ])
    write_csv(ad/"atomic_claims.csv",claims,[
        "claim_id","unit_id","content_id","start_seconds","end_seconds","speaker_id","claim_text","claim_type",
        "checkability","severity","target_entity_ids","claimant_entity_id","attribution_mode","requires_primary_source",
        "fact_check_status","source_path"
    ])
    write_csv(ad/"mentions.csv",mentions,[
        "mention_id","unit_id","content_id","start_seconds","end_seconds","speaker_id","surface","normalized_surface",
        "entity_type","canonical_entity_id","resolution_status","reference_mode","transcript_fragmented",
        "correction_candidate","confidence","source_path"
    ])
    write_csv(ad/"relationship_claims.csv",relationships,[
        "relationship_claim_id","unit_id","content_id","speaker_id","subject_entity_id","object_entity_id",
        "relationship_type","description","confidence","source_path"
    ])
    identity_clues_path=ad/"speaker_identity_clues.csv"
    write_csv(identity_clues_path,identity_clues,[
        "identity_clue_id","unit_id","content_id","channel_id","start_seconds","end_seconds","target_acoustic_cluster_id",
        "target_raw_speaker_id","current_canonical_voice_id","current_resolved_entity_id",
        "claimed_entity_id","claimed_name","evidence_type","evidence_text","confidence",
        "speaker_adoption","source_path"
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

    voice_identity_sync={"attempted":False}
    if not args.skip_voice_identity_sync and identity_clues and identity_clues_path.exists():
        repo_root=ad.parents[1] if len(ad.parents)>=2 else Path.cwd()
        voice_db=repo_root/"research"/"audio_identity"/"voice_identity.sqlite"
        identity_script=repo_root/"scripts"/"audio_identity_db.py"
        if voice_db.exists() and identity_script.exists():
            voice_identity_sync["attempted"]=True
            commands=[
                [sys.executable,str(identity_script),"--db",str(voice_db),"ingest-clues","--clues-csv",str(identity_clues_path)],
                [sys.executable,str(identity_script),"--db",str(voice_db),"fuse-identities"],
                [sys.executable,str(identity_script),"--db",str(voice_db),"export-hypotheses","--output",str(repo_root/"data"/"audio"/"identity_hypotheses.csv")],
                [sys.executable,str(identity_script),"--db",str(voice_db),"export","--output",str(repo_root/"data"/"audio"/"speaker_resolution_current.csv")],
            ]
            results=[]
            for cmd in commands:
                cp=subprocess.run(cmd,cwd=str(repo_root),stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
                results.append({"command":cmd[3] if len(cmd)>3 else "","exit_code":cp.returncode,"stdout":cp.stdout[-1000:],"stderr":cp.stderr[-1000:]})
                if cp.returncode:
                    voice_identity_sync["error"]=cp.stderr[-2000:] or cp.stdout[-2000:]
                    break
            voice_identity_sync["results"]=results

    print(json.dumps({
        "accepted_reviews":accepted,"total_reviews":len(reviews),"semantic_events":len(semantic_events),"claims":len(claims),
        "fact_checks_pending":len(unresolved),"mentions":len(mentions),"relationships":len(relationships),
        "stances":len(stances),"speaker_identity_clues":len(identity_clues),
        "voice_identity_sync":voice_identity_sync,"products":len(products),"predictions":len(predictions),"money_conflict_signals":len(money)
    },indent=2))
    return 0

if __name__=="__main__":
    raise SystemExit(main())
