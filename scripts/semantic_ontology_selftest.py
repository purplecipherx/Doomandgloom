#!/usr/bin/env python3
from __future__ import annotations

import csv, json
from collections import Counter
from pathlib import Path

FACT_STATUSES={
    "PENDING","VERIFIED","SUPPORTED_INFERENCE","DISPUTED","UNVERIFIED","CONTRADICTED",
    "OPINION_OR_NOT_CHECKABLE","NOT_APPLICABLE"
}
ADOPTION_REQUIRED_PREFIXES=("ACCUSES_","CALLS_")

def main():
    repo=Path(__file__).resolve().parents[1]
    ontology_path=repo/"data"/"ontology"/"investigative_predicates.csv"
    schema_path=repo/"data"/"ontology"/"semantic_event_schema.json"
    gold_path=repo/"data"/"analysis"/"gold"/"solari_semantic_gold_v1.jsonl"

    ontology=list(csv.DictReader(ontology_path.open(encoding="utf-8-sig")))
    codes=[r["predicate_code"] for r in ontology]
    assert len(codes)==len(set(codes)), "duplicate predicate codes"
    assert len(codes)>=400, f"ontology unexpectedly small: {len(codes)}"
    code_map={r["predicate_code"]:r for r in ontology}

    schema=json.loads(schema_path.read_text(encoding="utf-8"))
    assert schema["schema_version"]
    for required in ["predicate_code","raw_predicate","speaker_adoption","attribution_mode","certainty","explicitness","polarity"]:
        assert required in schema["required"], f"schema missing required field {required}"

    gold=[]
    for line in gold_path.read_text(encoding="utf-8").splitlines():
        if line.strip(): gold.append(json.loads(line))
    assert len(gold)>=16, f"gold set unexpectedly small: {len(gold)}"

    used=Counter()
    for g in gold:
        assert g.get("id") and g.get("video_id") and g.get("text")
        exp=g.get("expected") or {}
        for ev in exp.get("events") or []:
            pred=ev.get("predicate")
            assert pred in code_map, f"{g['id']}: unknown predicate {pred}"
            used[pred]+=1
            if pred.startswith(ADOPTION_REQUIRED_PREFIXES):
                assert ev.get("speaker_adoption"), f"{g['id']}: {pred} missing speaker_adoption"
        fs=exp.get("fact_status")
        if fs:
            assert fs in FACT_STATUSES, f"{g['id']}: invalid fact status {fs}"
        for rel in exp.get("relationship_edges") or []:
            pred=rel.get("predicate","")
            if pred:
                row=code_map.get(pred)
                assert row and row["relationship_graph_eligible"]!="NO", (
                    f"{g['id']}: discourse-only predicate {pred} incorrectly used as relationship edge"
                )

    families=Counter(r["family"] for r in ontology)
    required_families={
        "REFERENCE","POSITIVE_STANCE","NEGATIVE_STANCE","ALLEGATION","MEDIA_SOCIAL","COMMERCIAL",
        "FINANCE_OWNERSHIP","PROFESSIONAL_ORG","SOURCE_EVIDENCE","EPISTEMIC",
        "PREDICTION_WARNING","RHETORICAL_PERSUASION","LEGAL_REGULATORY","POLICY_POWER","EVENT_CAUSAL"
    }
    missing=required_families-set(families)
    assert not missing, f"missing ontology families: {sorted(missing)}"

    print(json.dumps({
        "ok":True,
        "ontology_predicates":len(codes),
        "ontology_families":dict(sorted(families.items())),
        "gold_cases":len(gold),
        "gold_predicates_used":len(used),
        "top_gold_predicates":used.most_common(12),
    },indent=2))
    return 0

if __name__=="__main__":
    raise SystemExit(main())
