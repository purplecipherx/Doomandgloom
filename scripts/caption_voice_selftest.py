#!/usr/bin/env python3
from __future__ import annotations

import csv
import json
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

def main():
    with tempfile.TemporaryDirectory(prefix="doomandgloom_captionvoice_") as td:
        root=Path(td)
        channel=root/"YTTEST"
        normalized=channel/"normalized"; normalized.mkdir(parents=True)
        voice_audio=channel/"voice_audio"/"VID1"; voice_audio.mkdir(parents=True)
        audio=voice_audio/"VID1.128k.opus"; audio.write_bytes(b"test")

        (normalized/"VID1.segments.jsonl").write_text(
            json.dumps({"start":1.0,"end":2.0,"text":"Clear speaker."})+"\n"+
            json.dumps({"start":3.0,"end":4.0,"text":"Speaker change."})+"\n",
            encoding="utf-8"
        )
        manifest=channel/"voice_audio"/"audio_manifest.jsonl"
        manifest.write_text(json.dumps({
            "video_id":"VID1","url":"https://example.invalid/VID1","title":"Test",
            "status":"downloaded","audio_path":"voice_audio/VID1/VID1.128k.opus","sha256":"abc"
        })+"\n",encoding="utf-8")

        moji=channel/"voice_index_work"; moji.mkdir()
        db=sqlite3.connect(moji/"voice_harvester.sqlite")
        db.executescript("""
        CREATE TABLE source_files(id INTEGER PRIMARY KEY,path TEXT);
        CREATE TABLE segments(id INTEGER PRIMARY KEY,file_id INTEGER,local_speaker TEXT,start REAL,end REAL,duration REAL,overlap INTEGER);
        CREATE TABLE local_speakers(id INTEGER PRIMARY KEY,file_id INTEGER,local_speaker TEXT);
        CREATE TABLE speaker_assignments(local_speaker_id INTEGER PRIMARY KEY,global_speaker_id TEXT,similarity REAL);
        """)
        db.execute("INSERT INTO source_files(id,path) VALUES(1,?)",(str(audio.resolve()),))
        db.execute("INSERT INTO local_speakers(id,file_id,local_speaker) VALUES(1,1,'SPEAKER_00')")
        db.execute("INSERT INTO local_speakers(id,file_id,local_speaker) VALUES(2,1,'SPEAKER_01')")
        db.execute("INSERT INTO speaker_assignments(local_speaker_id,global_speaker_id,similarity) VALUES(1,'SPK_TEST',0.99)")
        db.execute("INSERT INTO speaker_assignments(local_speaker_id,global_speaker_id,similarity) VALUES(2,'SPK_OTHER',0.99)")
        db.execute("INSERT INTO segments VALUES(1,1,'SPEAKER_00',0.8,2.2,1.4,0)")
        db.execute("INSERT INTO segments VALUES(2,1,'SPEAKER_00',3.0,3.5,0.5,0)")
        db.execute("INSERT INTO segments VALUES(3,1,'SPEAKER_01',3.5,4.0,0.5,0)")
        db.commit(); db.close()

        resolution=root/"resolution.csv"
        fields=["cluster_observation_id","pipeline_cluster_id","channel_id","canonical_voice_id","resolved_entity_id",
                "display_name","identity_status","binding_status","confidence","moji_output_path"]
        with resolution.open("w",newline="",encoding="utf-8-sig") as f:
            w=csv.DictWriter(f,fieldnames=fields); w.writeheader()
            w.writerow({
                "cluster_observation_id":"AC_TEST","pipeline_cluster_id":"SPK_TEST","channel_id":"YTTEST",
                "canonical_voice_id":"VOICE_00000001","resolved_entity_id":"person_test","display_name":"Test Person",
                "identity_status":"VERIFIED","binding_status":"VERIFIED","confidence":"1.0","moji_output_path":str(moji.resolve())
            })

        out=root/"out"
        script=Path(__file__).resolve().parent/"align_captions_to_speakers.py"
        cp=subprocess.run([
            sys.executable,str(script),
            "--moji-output",str(moji),"--normalized-dir",str(normalized),
            "--audio-manifest",str(manifest),"--speaker-resolution",str(resolution),
            "--channel-id","YTTEST","--output",str(out)
        ],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
        if cp.returncode:
            raise RuntimeError(cp.stderr or cp.stdout)

        rows=list(csv.DictReader((out/"caption_speaker_attribution.csv").open(encoding="utf-8-sig")))
        assert len(rows)==2,rows
        assert rows[0]["speaker_attribution_status"]=="ATTRIBUTED_HIGH",rows[0]
        assert rows[0]["resolved_entity_id"]=="person_test",rows[0]
        assert rows[1]["speaker_attribution_status"]=="AMBIGUOUS",rows[1]
        assert int(rows[1]["speaker_count"])==2,rows[1]
        print(json.dumps({
            "ok":True,
            "clear_status":rows[0]["speaker_attribution_status"],
            "clear_identity":rows[0]["resolved_entity_id"],
            "ambiguous_status":rows[1]["speaker_attribution_status"],
            "ambiguous_speakers":rows[1]["speaker_count"],
        },indent=2))
    return 0

if __name__=="__main__":
    raise SystemExit(main())
