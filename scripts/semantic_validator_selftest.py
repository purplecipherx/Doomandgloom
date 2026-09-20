#!/usr/bin/env python3
from __future__ import annotations

import csv,json,subprocess,sys,tempfile
from pathlib import Path

def run_validator(script,review,ontology,schema):
    return subprocess.run(
        [sys.executable,str(script),str(review),"--ontology",str(ontology),"--schema",str(schema)],
        stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True
    )

def main():
    repo=Path(__file__).resolve().parents[1]
    validator=repo/"scripts"/"validate_semantic_review_output.py"
    ontology=repo/"data"/"ontology"/"investigative_predicates.csv"
    schema=repo/"data"/"ontology"/"semantic_event_schema.json"

    with tempfile.TemporaryDirectory(prefix="doomandgloom_semantic_validator_") as td:
        td=Path(td)
        valid=td/"valid.jsonl"
        valid.write_text(json.dumps({
            "unit_id":"TU_TEST",
            "mentions":[{"surface":"Tucker Carlson","entity_type":"person"}],
            "atomic_claims":[{"claim_text":"X happened.","checkability":"CHECKABLE"}],
            "semantic_events":[{
                "predicate_code":"CRITICIZES",
                "predicate_family":"NEGATIVE_STANCE",
                "raw_predicate":"criticizes",
                "speaker_adoption":"ADOPTS",
                "attribution_mode":"OWN_CLAIM",
                "certainty":"ASSERTED",
                "explicitness":"EXPLICIT",
                "polarity":"NEGATIVE",
                "target_surface":"Tucker Carlson",
                "fact_check_need":"CHECKABLE"
            }]
        })+"\n",encoding="utf-8")
        cp=run_validator(validator,valid,ontology,schema)
        assert cp.returncode==0,(cp.stdout,cp.stderr)

        bad_unknown=td/"bad_unknown.jsonl"
        bad_unknown.write_text(json.dumps({
            "unit_id":"TU_BAD1","semantic_events":[{
                "predicate_code":"TOTALLY_MADE_UP","raw_predicate":"made up",
                "speaker_adoption":"ADOPTS","attribution_mode":"OWN_CLAIM",
                "certainty":"ASSERTED","explicitness":"EXPLICIT","polarity":"NEGATIVE"
            }]
        })+"\n",encoding="utf-8")
        cp=run_validator(validator,bad_unknown,ontology,schema)
        assert cp.returncode!=0,"unknown predicate should fail"

        bad_neutral=td/"bad_neutral.jsonl"
        bad_neutral.write_text(json.dumps({
            "unit_id":"TU_BAD2","semantic_events":[{
                "predicate_code":"ATTRIBUTES_TO_SOURCE","raw_predicate":"they say",
                "speaker_adoption":"NEUTRAL_REPORT","attribution_mode":"OWN_CLAIM",
                "certainty":"ASSERTED","explicitness":"EXPLICIT","polarity":"NEUTRAL"
            }]
        })+"\n",encoding="utf-8")
        cp=run_validator(validator,bad_neutral,ontology,schema)
        assert cp.returncode!=0,"neutral report as own claim should fail"

        bad_rel=td/"bad_rel.jsonl"
        bad_rel.write_text(json.dumps({
            "unit_id":"TU_BAD3","semantic_events":[{
                "predicate_code":"CRITICIZES","raw_predicate":"criticized",
                "speaker_adoption":"ADOPTS","attribution_mode":"OWN_CLAIM",
                "certainty":"ASSERTED","explicitness":"EXPLICIT","polarity":"NEGATIVE",
                "relationship_evidence_state":"DOCUMENTED"
            }]
        })+"\n",encoding="utf-8")
        cp=run_validator(validator,bad_rel,ontology,schema)
        assert cp.returncode!=0,"criticism must not create documented relationship"

        print(json.dumps({
            "ok":True,
            "valid_review":"accepted",
            "unknown_predicate":"rejected",
            "neutral_report_as_own_claim":"rejected",
            "criticism_as_documented_relationship":"rejected"
        },indent=2))
    return 0

if __name__=="__main__":
    raise SystemExit(main())
