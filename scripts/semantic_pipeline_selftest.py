#!/usr/bin/env python3
from __future__ import annotations

import csv,json,subprocess,sys,tempfile
from pathlib import Path

def run(cmd,cwd):
    cp=subprocess.run(cmd,cwd=str(cwd),stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
    if cp.returncode:
        raise RuntimeError(f"command failed {cmd}\nSTDOUT:\n{cp.stdout}\nSTDERR:\n{cp.stderr}")
    return cp

def write_csv(path,rows,fields):
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open("w",newline="",encoding="utf-8-sig") as f:
        w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(rows)

def main():
    repo=Path(__file__).resolve().parents[1]
    py=sys.executable
    with tempfile.TemporaryDirectory(prefix="doomandgloom_semantic_lifecycle_") as td:
        root=Path(td); ad=root/"analysis"; ad.mkdir()
        ledger=ad/"transcript_units.csv"
        fields=[
            "unit_id","source_sha256","source_type","source_path","content_id","canonical_url","title",
            "start_seconds","end_seconds","speaker_id","raw_speaker_id","acoustic_cluster_id",
            "canonical_voice_id","resolved_entity_id","speaker_resolution_status","speaker_resolution_confidence",
            "speaker_display_name","channel_id","text","unit_index","source_status","superseded_at",
            "semantic_review_status","fact_check_status","created_at","last_seen_at"
        ]
        write_csv(ledger,[{
            "unit_id":"TU_TEST","source_sha256":"abc","source_type":"youtube_caption","source_path":"test.jsonl",
            "content_id":"VID_TEST","canonical_url":"","title":"Test","start_seconds":"10","end_seconds":"15",
            "speaker_id":"SPK_TEST","raw_speaker_id":"SPK_TEST","acoustic_cluster_id":"AC_TEST",
            "canonical_voice_id":"VOICE_TEST","resolved_entity_id":"fitts_catherine","speaker_resolution_status":"VERIFIED",
            "speaker_resolution_confidence":"1.0","speaker_display_name":"Catherine Austin Fitts","channel_id":"YT001",
            "text":"The Trump family is grifting in crypto.","unit_index":"0","source_status":"CURRENT",
            "superseded_at":"","semantic_review_status":"PENDING","fact_check_status":"PENDING",
            "created_at":"2026-01-01T00:00:00+00:00","last_seen_at":"2026-01-01T00:00:00+00:00"
        }],fields)

        review=root/"review.jsonl"
        review.write_text(json.dumps({
            "unit_id":"TU_TEST","speaker_entity_id":"fitts_catherine",
            "semantic_events":[{
                "predicate_code":"ACCUSES_GRIFTING","raw_predicate":"is grifting",
                "source_entity_id":"fitts_catherine","target_surface":"Trump family",
                "predicate_family":"ALLEGATION","polarity":"NEGATIVE","speaker_adoption":"ADOPTS",
                "attribution_mode":"OWN_CLAIM","certainty":"ASSERTED","explicitness":"EXPLICIT",
                "fact_check_need":"HIGH_PRIORITY","severity":"HIGH","relationship_evidence_state":"NONE",
                "source_span_text":"The Trump family is grifting in crypto."
            }],
            "mentions":[{
                "surface":"Trump family","normalized_surface":"Trump family","entity_type":"person_group",
                "resolution_status":"UNRESOLVED","reference_mode":"EXPLICIT","transcript_fragmented":False,
                "correction_candidate":"","confidence":0.99
            }],
            "atomic_claims":[{
                "claim_text":"The Trump family is engaging in grifting in crypto.","claim_type":"misconduct_allegation",
                "checkability":"CHECKABLE","severity":"HIGH","target_entity_ids":[],
                "claimant_entity_id":"fitts_catherine","attribution_mode":"OWN_CLAIM","requires_primary_source":True
            }]
        })+"\n",encoding="utf-8")

        run([
            py,str(repo/"scripts"/"apply_semantic_review.py"),str(review),
            "--analysis-dir",str(ad),"--ontology",str(repo/"data"/"ontology"/"investigative_predicates.csv"),
            "--skip-voice-identity-sync"
        ],repo)

        events=list(csv.DictReader((ad/"semantic_events.csv").open(encoding="utf-8-sig")))
        assert len(events)==1
        assert events[0]["predicate_code"]=="ACCUSES_GRIFTING"
        assert events[0]["predicate_family"]=="ALLEGATION"

        # Before second-pass verification, default investigative views must exclude the event.
        out0=root/"views_before"
        run([
            py,str(repo/"scripts"/"build_investigative_semantic_views.py"),
            "--analysis-dir",str(ad),"--connections",str(repo/"data"/"connections.csv"),"--output-dir",str(out0)
        ],repo)
        before=list(csv.DictReader((out0/"entity_target_interactions.csv").open(encoding="utf-8-sig")))
        assert before==[],f"unverified event leaked into views: {before}"

        verification=root/"verify.jsonl"
        verification.write_text(json.dumps({
            "semantic_event_id":events[0]["semantic_event_id"],"status":"VERIFIED_TEXT",
            "error_types":[],"reviewer":"selftest","reviewed_at":"2026-01-01T00:00:01+00:00",
            "reasoning_summary":"Transcript explicitly supports that the speaker makes the allegation."
        })+"\n",encoding="utf-8")
        run([
            py,str(repo/"scripts"/"apply_semantic_event_verification.py"),str(verification),
            "--events",str(ad/"semantic_events.csv"),"--output",str(ad/"semantic_event_verifications.csv")
        ],repo)

        out1=root/"views_after"
        run([
            py,str(repo/"scripts"/"build_investigative_semantic_views.py"),
            "--analysis-dir",str(ad),"--connections",str(repo/"data"/"connections.csv"),"--output-dir",str(out1)
        ],repo)
        after=list(csv.DictReader((out1/"entity_target_interactions.csv").open(encoding="utf-8-sig")))
        assert len(after)==1,after
        assert after[0]["source"]=="fitts_catherine"
        assert after[0]["target"]=="Trump family"
        assert int(after[0]["allegation_count"])==1
        assert int(after[0]["negative_count"])==1

        fq=list(csv.DictReader((ad/"fact_check_queue.csv").open(encoding="utf-8-sig")))
        assert len(fq)==1 and fq[0]["claimant_entity_id"]=="fitts_catherine" if "claimant_entity_id" in fq[0] else len(fq)==1

        print(json.dumps({
            "ok":True,
            "unverified_events_in_views":len(before),
            "verified_events_in_views":len(after),
            "allegation_count":after[0]["allegation_count"],
            "fact_check_queue":len(fq)
        },indent=2))
    return 0

if __name__=="__main__":
    raise SystemExit(main())
