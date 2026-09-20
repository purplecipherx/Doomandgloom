#!/usr/bin/env python3
from __future__ import annotations

import argparse,json
from collections import Counter,defaultdict
from pathlib import Path

CRITICAL_ERRORS={
    "MENTION_TO_RELATIONSHIP":12,
    "CRITICISM_TO_ASSOCIATION":12,
    "QUOTE_TO_BELIEF":12,
    "HEARSAY_TO_BELIEF":12,
    "ALLEGATION_TO_FACT":15,
    "NEGATION_INVERSION":15,
    "WRONG_CLAIMANT":15,
    "WRONG_TARGET":12,
    "COREFERENCE_GUESSED":12,
    "RECOMMENDATION_TO_AFFILIATE":12,
    "PREDICTION_TO_OBSERVED_EVENT":12,
    "HYPOTHETICAL_TO_ASSERTION":12,
    "QUESTION_TO_ASSERTION":10,
    "SHARED_TARGET_TO_COORDINATION":15,
}

def norm(s):
    return " ".join(str(s or "").lower().split())

def load_jsonl(path):
    return [json.loads(x) for x in Path(path).read_text(encoding="utf-8").splitlines() if x.strip()]

def set_prf(gold,pred):
    gs=set(gold); ps=set(pred)
    tp=len(gs&ps); fp=len(ps-gs); fn=len(gs-ps)
    p=tp/(tp+fp) if tp+fp else 1.0
    r=tp/(tp+fn) if tp+fn else 1.0
    f=2*p*r/(p+r) if p+r else 0.0
    return {"tp":tp,"fp":fp,"fn":fn,"precision":p,"recall":r,"f1":f}

def event_key(e):
    return (
        (e.get("predicate_code") or e.get("predicate") or "").upper(),
        norm(e.get("target_entity_id") or e.get("target_surface") or e.get("target") or ""),
        (e.get("speaker_adoption") or "ADOPTS").upper(),
    )

def mention_key(m):
    return norm(m.get("canonical_entity_id") or m.get("surface") or m.get("text") or "")

def claim_key(c):
    return norm(c.get("claim_text") or c.get("claim") or "")

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--gold",default="data/analysis/gold/solari_semantic_gold_v1.jsonl")
    ap.add_argument("--predictions",required=True)
    ap.add_argument("--output",default="")
    args=ap.parse_args()

    gold=load_jsonl(args.gold)
    pred=load_jsonl(args.predictions)
    gm={r["id"]:r for r in gold}
    pm={r.get("gold_id") or r.get("id"):r for r in pred}

    mention_gold=[];mention_pred=[];event_gold=[];event_pred=[];claim_gold=[];claim_pred=[]
    case_rows=[];critical=Counter(); missing_cases=[];extra_cases=[]

    for gid,g in gm.items():
        p=pm.get(gid)
        if p is None:
            missing_cases.append(gid); p={}
        ge=[event_key(e) for e in (g.get("expected",{}).get("events") or [])]
        pe=[event_key(e) for e in (p.get("semantic_events") or p.get("events") or [])]
        gmns=[mention_key(m) for m in (g.get("expected",{}).get("mentions") or []) if mention_key(m)]
        pmns=[mention_key(m) for m in (p.get("mentions") or []) if mention_key(m)]
        gc=[claim_key(c) for c in (g.get("expected",{}).get("atomic_claims") or []) if claim_key(c)]
        pc=[claim_key(c) for c in (p.get("atomic_claims") or []) if claim_key(c)]
        mention_gold.extend((gid,x) for x in gmns);mention_pred.extend((gid,x) for x in pmns)
        event_gold.extend((gid,x) for x in ge);event_pred.extend((gid,x) for x in pe)
        claim_gold.extend((gid,x) for x in gc);claim_pred.extend((gid,x) for x in pc)
        errs=p.get("critical_errors") or []
        for e in errs:critical[str(e).upper()]+=1
        case_rows.append({
            "id":gid,
            "mentions":set_prf(gmns,pmns),
            "events":set_prf(ge,pe),
            "claims":set_prf(gc,pc),
            "critical_errors":[str(x).upper() for x in errs],
        })

    for pid in pm:
        if pid not in gm: extra_cases.append(pid)

    scores={
        "mentions":set_prf(mention_gold,mention_pred),
        "semantic_events":set_prf(event_gold,event_pred),
        "atomic_claims":set_prf(claim_gold,claim_pred),
    }
    critical_penalty=sum(CRITICAL_ERRORS.get(k,5)*v for k,v in critical.items())
    weighted_quality=max(0.0,100.0-critical_penalty)
    result={
        "gold_cases":len(gm),"prediction_cases":len(pm),
        "missing_cases":missing_cases,"extra_cases":extra_cases,
        "scores":scores,
        "critical_errors":dict(critical),
        "critical_error_penalty":critical_penalty,
        "critical_safety_score":weighted_quality,
        "case_results":case_rows,
        "acceptance_targets":{
            "entity_recall_min":0.98,
            "event_precision_min":0.97,
            "event_recall_min":0.95,
            "critical_errors_max":0,
            "note":"Targets are engineering gates for this corpus, not claims of universal model accuracy."
        }
    }
    text=json.dumps(result,indent=2,ensure_ascii=False)
    print(text)
    if args.output:Path(args.output).write_text(text+"\n",encoding="utf-8")
    return 0

if __name__=="__main__":
    raise SystemExit(main())
