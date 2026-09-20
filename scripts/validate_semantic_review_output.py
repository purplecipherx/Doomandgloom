#!/usr/bin/env python3
from __future__ import annotations

import argparse,csv,json
from pathlib import Path

TRUTHY={"true","1","yes","y"}
FACT_VERDICT_WORDS={"TRUE","FALSE","ACCURATE","INACCURATE","DEFAMATORY","SLANDEROUS","LIBELOUS"}

def b(v):
    if isinstance(v,bool): return v
    return str(v or "").strip().lower() in TRUTHY

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("review_jsonl")
    ap.add_argument("--ontology",default="data/ontology/investigative_predicates.csv")
    ap.add_argument("--schema",default="data/ontology/semantic_event_schema.json")
    args=ap.parse_args()

    repo=Path(__file__).resolve().parents[1]
    ontology_path=(repo/args.ontology).resolve() if not Path(args.ontology).is_absolute() else Path(args.ontology)
    schema_path=(repo/args.schema).resolve() if not Path(args.schema).is_absolute() else Path(args.schema)
    ontology={r["predicate_code"]:r for r in csv.DictReader(ontology_path.open(encoding="utf-8-sig"))}
    schema=json.loads(schema_path.read_text(encoding="utf-8"))

    errors=[]; warnings=[]; units=0; events=0; mentions=0
    for line_no,line in enumerate(Path(args.review_jsonl).read_text(encoding="utf-8").splitlines(),1):
        if not line.strip():continue
        units+=1
        try:r=json.loads(line)
        except Exception as e:
            errors.append(f"line {line_no}: invalid JSON: {e}"); continue
        uid=r.get("unit_id") or f"line {line_no}"
        for m in r.get("mentions") or []:
            mentions+=1
            if not (m.get("surface") or m.get("text")):
                errors.append(f"{uid}: mention without surface")
            if b(m.get("transcript_fragmented")) and not m.get("correction_candidate"):
                warnings.append(f"{uid}: fragmented mention without correction_candidate")

        claim_ids={c.get("claim_id") for c in (r.get("atomic_claims") or []) if c.get("claim_id")}
        for ev in r.get("semantic_events") or []:
            events+=1
            pred=(ev.get("predicate_code") or "").upper()
            if pred not in ontology:
                errors.append(f"{uid}: unknown predicate {pred}")
                continue
            for field in schema["required"]:
                if ev.get(field) in (None,""):
                    errors.append(f"{uid}: {pred} missing required field {field}")
            fam=(ev.get("predicate_family") or "").upper()
            expected=ontology[pred]["family"].upper()
            if fam and fam!=expected:
                errors.append(f"{uid}: {pred} family {fam} != ontology {expected}")
            if any(x in pred for x in FACT_VERDICT_WORDS):
                errors.append(f"{uid}: truth/legal verdict leaked into semantic predicate {pred}")
            if pred.startswith(("ACCUSES_","CALLS_")) and (ev.get("speaker_adoption") or "").upper()=="":
                errors.append(f"{uid}: {pred} missing adoption")
            if (ev.get("speaker_adoption") or "").upper()=="NEUTRAL_REPORT" and (ev.get("attribution_mode") or "").upper()=="OWN_CLAIM":
                errors.append(f"{uid}: neutral report cannot be OWN_CLAIM")
            if (ev.get("relationship_evidence_state") or "").upper()=="DOCUMENTED":
                if ontology[pred]["relationship_graph_eligible"]=="NO":
                    errors.append(f"{uid}: discourse predicate {pred} cannot create documented relationship")
            if (ev.get("fact_check_need") or "").upper() in {"CHECKABLE","PARTLY_CHECKABLE","HIGH_PRIORITY"}:
                if not (r.get("atomic_claims") or []):
                    warnings.append(f"{uid}: {pred} requires fact check but unit has no atomic_claims")
            if b(ev.get("negated")) and (ev.get("speaker_adoption") or "").upper()=="ADOPTS":
                warnings.append(f"{uid}: check negated ADOPTS event {pred} for inversion")

    print(json.dumps({
        "ok":not errors,"units":units,"semantic_events":events,"mentions":mentions,
        "error_count":len(errors),"warning_count":len(warnings),
        "errors":errors[:100],"warnings":warnings[:100]
    },indent=2))
    return 0 if not errors else 1

if __name__=="__main__":
    raise SystemExit(main())
