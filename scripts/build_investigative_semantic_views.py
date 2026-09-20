#!/usr/bin/env python3
from __future__ import annotations

import argparse,csv,json
from collections import Counter,defaultdict
from pathlib import Path

PROMO={
    "RECOMMENDS","RECOMMENDS_AS_SOURCE","RECOMMENDS_SHOW","RECOMMENDS_CHANNEL","RECOMMENDS_NEWSLETTER",
    "PROMOTES_PRODUCT","RECOMMENDS_PRODUCT","ADVERTISES","AFFILIATE_PROMOTES","CALLS_TO_BUY",
    "CALLS_TO_SUBSCRIBE","CALLS_TO_DONATE","CALLS_TO_INVEST","CROSS_PROMOTES","LINKS_AUDIENCE_TO"
}
ALLEGATION_PREFIX="ACCUSES_"
RHETORIC={
    "FEAR_APPEAL","URGENCY_APPEAL","SCARCITY_APPEAL","EXCLUSIVITY_APPEAL","AUTHORITY_APPEAL",
    "INSIDER_APPEAL","MORAL_APPEAL","PATRIOTIC_APPEAL","RELIGIOUS_APPEAL","ANGER_APPEAL",
    "DISGUST_APPEAL","HOPE_APPEAL","GREED_APPEAL","SOCIAL_PROOF_APPEAL","US_VS_THEM_FRAMING",
    "ENEMY_FRAMING","VICTIM_FRAMING","HERO_FRAMING","SCAPEGOAT_FRAMING","INEVITABILITY_FRAMING",
    "CATASTROPHE_FRAMING","CONSPIRACY_FRAMING","SECRECY_FRAMING","ISSUES_URGENCY","ISSUES_CALL_TO_PREPARE"
}
COMPLETED_FACT={"VERIFIED","SUPPORTED_INFERENCE","DISPUTED","UNVERIFIED","CONTRADICTED","OPINION_OR_NOT_CHECKABLE","NOT_APPLICABLE"}

def read_csv(path):
    p=Path(path)
    if not p.exists(): return []
    return list(csv.DictReader(p.open(encoding="utf-8-sig")))

def write_csv(path,rows,fields):
    p=Path(path); p.parent.mkdir(parents=True,exist_ok=True)
    with p.open("w",newline="",encoding="utf-8-sig") as f:
        w=csv.DictWriter(f,fieldnames=fields); w.writeheader()
        for r in rows:w.writerow({k:r.get(k,"") for k in fields})

def key_target(e):
    return e.get("target_entity_id") or e.get("target_surface") or e.get("target_claim_id") or ""

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--analysis-dir",default="data/analysis")
    ap.add_argument("--connections",default="data/connections.csv")
    ap.add_argument("--output-dir",default="data/analysis/views")
    ap.add_argument("--include-unverified-text-events",action="store_true")
    args=ap.parse_args()

    ad=Path(args.analysis_dir).resolve()
    out=Path(args.output_dir).resolve()
    events=read_csv(ad/"semantic_events.csv")
    verifications={r.get("semantic_event_id",""):r for r in read_csv(ad/"semantic_event_verifications.csv")}
    if not args.include_unverified_text_events:
        if verifications:
            events=[e for e in events if verifications.get(e.get("semantic_event_id",""),{}).get("status")=="VERIFIED_TEXT"]
        else:
            events=[]
    claims=read_csv(ad/"atomic_claims.csv")
    fact_checks=read_csv(ad/"fact_checks.csv")
    products=read_csv(ad/"product_mentions.csv")
    connections=read_csv(Path(args.connections).resolve())

    fact_by_claim={r.get("claim_id",""):r for r in fact_checks}
    claims_by_unit=defaultdict(list)
    for c in claims: claims_by_unit[c.get("unit_id","")].append(c)
    products_by_unit=defaultdict(list)
    for p in products: products_by_unit[p.get("unit_id","")].append(p)

    # 1. Source -> target interaction summaries.
    pairs=defaultdict(lambda:{
        "contents":set(),"units":set(),"predicates":Counter(),"topics":Counter(),
        "positive":0,"negative":0,"neutral":0,"mixed":0,"allegations":0,"promotions":0,
        "rhetorical_events":0,"checkable_events":0
    })
    for e in events:
        src=e.get("source_entity_id") or e.get("source_surface") or e.get("speaker_id") or "UNKNOWN"
        tgt=key_target(e)
        if not tgt: continue
        d=pairs[(src,tgt)]
        d["contents"].add(e.get("content_id","")); d["units"].add(e.get("unit_id",""))
        d["predicates"][e.get("predicate_code","")]+=1
        if e.get("topic"): d["topics"][e["topic"]]+=1
        pol=(e.get("polarity") or "").lower()
        if pol in d:d[pol]+=1
        pred=e.get("predicate_code","")
        if pred.startswith(ALLEGATION_PREFIX):d["allegations"]+=1
        if pred in PROMO:d["promotions"]+=1
        if pred in RHETORIC:d["rhetorical_events"]+=1
        if (e.get("fact_check_need") or "") in {"CHECKABLE","PARTLY_CHECKABLE","HIGH_PRIORITY"}:d["checkable_events"]+=1

    pair_rows=[]
    for (src,tgt),d in pairs.items():
        pair_rows.append({
            "source":src,"target":tgt,"event_count":sum(d["predicates"].values()),
            "independent_content_count":len([x for x in d["contents"] if x]),
            "unit_count":len([x for x in d["units"] if x]),
            "positive_count":d["positive"],"negative_count":d["negative"],"neutral_count":d["neutral"],"mixed_count":d["mixed"],
            "allegation_count":d["allegations"],"promotion_count":d["promotions"],
            "rhetorical_event_count":d["rhetorical_events"],"checkable_event_count":d["checkable_events"],
            "predicate_counts_json":json.dumps(d["predicates"],ensure_ascii=False,sort_keys=True),
            "topic_counts_json":json.dumps(d["topics"],ensure_ascii=False,sort_keys=True),
            "mixed_stance":str(d["positive"]>0 and d["negative"]>0).lower()
        })
    pair_rows.sort(key=lambda r:(-r["event_count"],-r["negative_count"],r["source"],r["target"]))
    write_csv(out/"entity_target_interactions.csv",pair_rows,[
        "source","target","event_count","independent_content_count","unit_count","positive_count","negative_count",
        "neutral_count","mixed_count","allegation_count","promotion_count","rhetorical_event_count",
        "checkable_event_count","predicate_counts_json","topic_counts_json","mixed_stance"
    ])

    # 2. Target pressure/support landscape.
    targets=defaultdict(lambda:{
        "sources":set(),"positive_sources":set(),"negative_sources":set(),"allegation_sources":set(),
        "promoter_sources":set(),"events":0,"positive":0,"negative":0,"allegations":0,"promotions":0
    })
    for r in pair_rows:
        d=targets[r["target"]]; d["sources"].add(r["source"]); d["events"]+=r["event_count"]
        d["positive"]+=r["positive_count"]; d["negative"]+=r["negative_count"]; d["allegations"]+=r["allegation_count"]; d["promotions"]+=r["promotion_count"]
        if r["positive_count"]:d["positive_sources"].add(r["source"])
        if r["negative_count"]:d["negative_sources"].add(r["source"])
        if r["allegation_count"]:d["allegation_sources"].add(r["source"])
        if r["promotion_count"]:d["promoter_sources"].add(r["source"])
    target_rows=[]
    for tgt,d in targets.items():
        target_rows.append({
            "target":tgt,"event_count":d["events"],"distinct_sources":len(d["sources"]),
            "positive_event_count":d["positive"],"negative_event_count":d["negative"],
            "distinct_positive_sources":len(d["positive_sources"]),"distinct_negative_sources":len(d["negative_sources"]),
            "allegation_count":d["allegations"],"distinct_allegation_sources":len(d["allegation_sources"]),
            "promotion_count":d["promotions"],"distinct_promoter_sources":len(d["promoter_sources"])
        })
    target_rows.sort(key=lambda r:(-r["distinct_negative_sources"],-r["negative_event_count"],-r["event_count"],r["target"]))
    write_csv(out/"target_pressure_support.csv",target_rows,[
        "target","event_count","distinct_sources","positive_event_count","negative_event_count",
        "distinct_positive_sources","distinct_negative_sources","allegation_count","distinct_allegation_sources",
        "promotion_count","distinct_promoter_sources"
    ])

    # 3. Shared-target source pairs, kept descriptive.
    by_target=defaultdict(list)
    for r in pair_rows:
        if r["negative_count"] or r["positive_count"] or r["promotion_count"]:
            by_target[r["target"]].append(r)
    shared=[]
    for tgt,rs in by_target.items():
        for i,a in enumerate(rs):
            for b in rs[i+1:]:
                if a["source"]==b["source"]:continue
                shared_neg=min(a["negative_count"],b["negative_count"])
                shared_pos=min(a["positive_count"],b["positive_count"])
                shared_promo=min(a["promotion_count"],b["promotion_count"])
                if not (shared_neg or shared_pos or shared_promo):continue
                shared.append({
                    "target":tgt,"source_a":a["source"],"source_b":b["source"],
                    "both_negative":str(bool(shared_neg)).lower(),"both_positive":str(bool(shared_pos)).lower(),
                    "both_promote":str(bool(shared_promo)).lower(),
                    "a_negative":a["negative_count"],"b_negative":b["negative_count"],
                    "a_positive":a["positive_count"],"b_positive":b["positive_count"],
                    "a_promotions":a["promotion_count"],"b_promotions":b["promotion_count"],
                    "note":"Shared target/stance is an investigative lead only; it does not establish coordination."
                })
    shared.sort(key=lambda r:(r["target"],r["source_a"],r["source_b"]))
    write_csv(out/"shared_target_source_pairs.csv",shared,[
        "target","source_a","source_b","both_negative","both_positive","both_promote",
        "a_negative","b_negative","a_positive","b_positive","a_promotions","b_promotions","note"
    ])

    # 4. Rhetoric -> commerce co-occurrence at unit/content level.
    rhetoric_by_content=defaultdict(list)
    for e in events:
        if e.get("predicate_code") in RHETORIC:
            rhetoric_by_content[e.get("content_id","")].append(e)
    product_by_content=defaultdict(list)
    for p in products:
        product_by_content[p.get("content_id","")].append(p)
    rc=[]
    for cid,revs in rhetoric_by_content.items():
        prods=product_by_content.get(cid,[])
        if not prods: continue
        rc.append({
            "content_id":cid,
            "rhetorical_event_count":len(revs),
            "rhetorical_predicates_json":json.dumps(Counter(e.get("predicate_code","") for e in revs),sort_keys=True),
            "product_mention_count":len(prods),
            "products_json":json.dumps(sorted({p.get("name","") for p in prods if p.get("name")}),ensure_ascii=False),
            "note":"Co-occurrence only; financial benefit or causal linkage requires separate evidence."
        })
    rc.sort(key=lambda r:(-r["rhetorical_event_count"],-r["product_mention_count"],r["content_id"]))
    write_csv(out/"rhetoric_commerce_cooccurrence.csv",rc,[
        "content_id","rhetorical_event_count","rhetorical_predicates_json","product_mention_count","products_json","note"
    ])

    # 5. Reputational/misconduct allegation resolution. This is descriptive;
    # legal labels such as defamation/libel/slander are not inferred here.
    claim_by_id={c.get("claim_id",""):c for c in claims}
    reputational=[]
    for e in events:
        pred=e.get("predicate_code","")
        if not (pred.startswith("ACCUSES_") or pred in {
            "CALLS_DISHONEST","CALLS_FRAUDULENT","CALLS_SCAM","CALLS_LIE",
            "CALLS_CORRUPT","CALLS_COMPROMISED","QUESTIONS_CREDIBILITY","QUESTIONS_MOTIVES"
        }):
            continue
        try:
            linked=json.loads(e.get("related_claim_ids_json") or "[]")
        except Exception:
            linked=[]
        if not linked:
            reputational.append({
                "semantic_event_id":e.get("semantic_event_id",""),"source":e.get("source_entity_id") or e.get("speaker_id",""),
                "target":key_target(e),"predicate_code":pred,"severity":e.get("severity",""),
                "claim_id":"","claim_text":"","fact_status":"NO_LINKED_CLAIM",
                "content_id":e.get("content_id",""),"unit_id":e.get("unit_id",""),
                "note":"Semantically verified allegation; no linked atomic claim yet."
            })
            continue
        for cid in linked:
            c=claim_by_id.get(cid,{})
            status=(fact_by_claim.get(cid,{}).get("status") or c.get("fact_check_status") or "PENDING").upper()
            reputational.append({
                "semantic_event_id":e.get("semantic_event_id",""),"source":e.get("source_entity_id") or e.get("speaker_id",""),
                "target":key_target(e),"predicate_code":pred,"severity":e.get("severity",""),
                "claim_id":cid,"claim_text":c.get("claim_text",""),"fact_status":status,
                "content_id":e.get("content_id",""),"unit_id":e.get("unit_id",""),
                "note":"Fact status describes the proposition; it is not a legal defamation/libel/slander determination."
            })
    reputational.sort(key=lambda r:(r["fact_status"],r["target"],r["source"],r["predicate_code"]))
    write_csv(out/"reputational_allegations_and_fact_status.csv",reputational,[
        "semantic_event_id","source","target","predicate_code","severity","claim_id","claim_text",
        "fact_status","content_id","unit_id","note"
    ])

    # 5. Claim accuracy/status by source after fact checking.
    source_claims=defaultdict(Counter)
    for c in claims:
        src=c.get("claimant_entity_id") or c.get("speaker_id") or "UNKNOWN"
        status=(fact_by_claim.get(c.get("claim_id",""),{}).get("status") or c.get("fact_check_status") or "PENDING").upper()
        source_claims[src]["total"]+=1; source_claims[src][status]+=1
    acc=[]
    for src,d in source_claims.items():
        completed=sum(d[s] for s in COMPLETED_FACT)
        acc.append({
            "source":src,"claim_count":d["total"],"completed_fact_checks":completed,
            "verified":d["VERIFIED"],"supported_inference":d["SUPPORTED_INFERENCE"],"disputed":d["DISPUTED"],
            "unverified":d["UNVERIFIED"],"contradicted":d["CONTRADICTED"],
            "opinion_or_not_checkable":d["OPINION_OR_NOT_CHECKABLE"],"pending":d["PENDING"],
            "note":"Descriptive fact-check counts; not an overall credibility score."
        })
    acc.sort(key=lambda r:(-r["claim_count"],r["source"]))
    write_csv(out/"claim_status_by_source.csv",acc,[
        "source","claim_count","completed_fact_checks","verified","supported_inference","disputed","unverified",
        "contradicted","opinion_or_not_checkable","pending","note"
    ])

    print(json.dumps({
        "semantic_events_used":len(events),"text_verification_required":not args.include_unverified_text_events,
        "pair_summaries":len(pair_rows),"targets":len(target_rows),
        "shared_target_pairs":len(shared),"rhetoric_commerce_rows":len(rc),
        "reputational_allegation_rows":len(reputational),"claim_source_rows":len(acc),
        "output_dir":str(out)
    },indent=2))
    return 0

if __name__=="__main__":
    raise SystemExit(main())
