#!/usr/bin/env python3
from __future__ import annotations

import csv,json,tempfile
from pathlib import Path

from queue_semantic_review import load_caption_attributions, attribution_for

def main():
    with tempfile.TemporaryDirectory(prefix="doomandgloom_semantic_attr_") as td:
        root=Path(td)
        p=root/"YT001"/"speaker_attribution"/"caption_speaker_attribution.csv"
        p.parent.mkdir(parents=True)
        fields=[
            "channel_id","video_id","start_seconds","end_seconds","text","raw_speaker_id",
            "acoustic_cluster_id","canonical_voice_id","resolved_entity_id","speaker_display_name",
            "speaker_resolution_status","speaker_resolution_confidence","speaker_attribution_status",
            "speaker_coverage_ratio","dominant_speaker_share","second_speaker_share","speaker_count",
            "candidate_speakers_json"
        ]
        rows=[
            {
                "channel_id":"YT001","video_id":"VID1","start_seconds":"10.0","end_seconds":"14.0",
                "text":"rolling cue one","raw_speaker_id":"SPK_A","acoustic_cluster_id":"AC_A",
                "canonical_voice_id":"VOICE_A","resolved_entity_id":"person_a","speaker_display_name":"Person A",
                "speaker_resolution_status":"VERIFIED","speaker_resolution_confidence":"1.0",
                "speaker_attribution_status":"ATTRIBUTED_HIGH","speaker_coverage_ratio":"1",
                "dominant_speaker_share":"0.95","second_speaker_share":"0.05","speaker_count":"1",
                "candidate_speakers_json":json.dumps([{"speaker_id":"SPK_A","share":1.0}])
            },
            {
                "channel_id":"YT001","video_id":"VID1","start_seconds":"12.0","end_seconds":"16.0",
                "text":"rolling cue two","raw_speaker_id":"SPK_A","acoustic_cluster_id":"AC_A",
                "canonical_voice_id":"VOICE_A","resolved_entity_id":"person_a","speaker_display_name":"Person A",
                "speaker_resolution_status":"VERIFIED","speaker_resolution_confidence":"1.0",
                "speaker_attribution_status":"ATTRIBUTED_HIGH","speaker_coverage_ratio":"1",
                "dominant_speaker_share":"0.9","second_speaker_share":"0.1","speaker_count":"1",
                "candidate_speakers_json":json.dumps([{"speaker_id":"SPK_A","share":1.0}])
            }
        ]
        with p.open("w",newline="",encoding="utf-8-sig") as f:
            w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(rows)

        attribution=load_caption_attributions(root)
        reconstructed={
            "content_id":"VID1","start_seconds":"10.5","end_seconds":"15.5",
            "text":"This is a reconstructed semantic sentence that does not equal either raw cue."
        }
        a=attribution_for(reconstructed,attribution)
        assert a["raw_speaker_id"]=="SPK_A",a
        assert a["resolved_entity_id"]=="person_a",a
        assert a["speaker_attribution_status"]=="ATTRIBUTED_HIGH",a
        assert float(a["speaker_coverage_ratio"])>0.95,a
        print(json.dumps({
            "ok":True,"speaker":a["raw_speaker_id"],"resolved_entity":a["resolved_entity_id"],
            "status":a["speaker_attribution_status"],"coverage":a["speaker_coverage_ratio"]
        },indent=2))
    return 0

if __name__=="__main__":
    raise SystemExit(main())
