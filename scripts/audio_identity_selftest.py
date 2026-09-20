#!/usr/bin/env python3
from __future__ import annotations

import csv
import json
import tempfile
from pathlib import Path

from audio_identity_db import connect, build_candidates, new_voice, bind, ingest_identity_clues, fuse_identity_hypotheses

def main():
    with tempfile.TemporaryDirectory(prefix="doomandgloom_voiceid_") as td:
        root=Path(td)
        db=root/"voice.sqlite"
        conn=connect(db)
        ts="2026-01-01T00:00:00+00:00"

        clusters=[
            ("AC_A","SPK_A","YT001",[1.0,0.0,0.0]),
            ("AC_B","SPK_B","YT002",[0.999,0.02,0.0]),
            ("AC_C","SPK_C","YT003",[0.0,1.0,0.0]),
        ]
        for obs,pid,ch,cent in clusters:
            conn.execute(
                """INSERT INTO acoustic_clusters(
                   cluster_observation_id,pipeline_cluster_id,channel_id,moji_output_path,
                   embedding_model,centroid_json,member_count,speech_seconds,created_at,source_manifest_path
                ) VALUES(?,?,?,?,?,?,?,?,?,?)""",
                (obs,pid,ch,str(root/ch),"test",json.dumps(cent),1,30.0,ts,str(root/"manifest.json"))
            )
        conn.commit()

        n=build_candidates(conn,0.8)
        assert n>=1
        n_again=build_candidates(conn,0.8)
        assert n_again==0, f"incremental matcher recomputed {n_again} pair(s)"

        voice=new_voice(conn,"Test Speaker","entity_test","VERIFIED",1.0,"selftest")
        bind(conn,"AC_A",voice,"VERIFIED",1.0,{"selftest":True},"selftest")

        clues=root/"clues.csv"
        fields=[
            "identity_clue_id","unit_id","content_id","channel_id","start_seconds","end_seconds",
            "target_acoustic_cluster_id","target_raw_speaker_id","current_canonical_voice_id",
            "current_resolved_entity_id","claimed_entity_id","claimed_name","evidence_type",
            "evidence_text","confidence","speaker_adoption","source_path"
        ]
        with clues.open("w",newline="",encoding="utf-8-sig") as f:
            w=csv.DictWriter(f,fieldnames=fields); w.writeheader()
            w.writerow({
                "identity_clue_id":"IC_TEST","unit_id":"TU_TEST","content_id":"VID_TEST","channel_id":"YT002",
                "start_seconds":"1.0","end_seconds":"3.0","target_acoustic_cluster_id":"AC_B",
                "target_raw_speaker_id":"SPK_B","current_canonical_voice_id":"","current_resolved_entity_id":"",
                "claimed_entity_id":"entity_test","claimed_name":"Test Speaker","evidence_type":"HOST_INTRODUCTION",
                "evidence_text":"Welcome Test Speaker","confidence":"1.0","speaker_adoption":"ADOPTS","source_path":"test"
            })

        assert ingest_identity_clues(conn,clues)==1
        fuse_identity_hypotheses(conn)
        h=conn.execute(
            "SELECT * FROM identity_hypotheses WHERE cluster_observation_id='AC_B' AND candidate_entity_id='entity_test'"
        ).fetchone()
        assert h is not None
        assert float(h["acoustic_score"])>0.7
        assert float(h["context_score"])>0.9
        assert h["status"]=="HIGH_CONFIDENCE_CANDIDATE"

        weak=conn.execute(
            "SELECT COUNT(*) FROM identity_hypotheses WHERE cluster_observation_id='AC_C' AND candidate_entity_id='entity_test'"
        ).fetchone()[0]
        assert weak==0

        print(json.dumps({
            "ok":True,
            "voice_match_candidates":conn.execute("SELECT COUNT(*) FROM voice_match_candidates").fetchone()[0],
            "second_match_pass_new_pairs":n_again,
            "hypothesis_status":h["status"],
            "context_score":h["context_score"],
            "acoustic_score":h["acoustic_score"],
            "combined_score":h["combined_score"],
        },indent=2))
        conn.close()
    return 0

if __name__=="__main__":
    raise SystemExit(main())
