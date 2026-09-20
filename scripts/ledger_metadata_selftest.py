#!/usr/bin/env python3
from __future__ import annotations

import csv,json,subprocess,sys,tempfile
from pathlib import Path

def main():
    repo=Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory(prefix="doomandgloom_ledger_meta_") as td:
        root=Path(td)
        research=root/"research"/"youtube"
        prod=research/"YT001"
        testch=research/"test_channel"
        for base in (prod,testch):
            (base/"normalized").mkdir(parents=True)
            (base/"metadata").mkdir(parents=True)

        cues=[
            {"start":1.0,"end":2.0,"text":"Welcome Catherine Austin Fitts"},
            {"start":2.0,"end":4.0,"text":"Welcome Catherine Austin Fitts to the show today."},
            {"start":4.0,"end":4.1,"text":"to the show today."},
        ]
        for base,vid in ((prod,"VID_PROD"),(testch,"VID_TEST")):
            (base/"normalized"/f"{vid}.segments.jsonl").write_text(
                "\n".join(json.dumps(x) for x in cues)+"\n",encoding="utf-8"
            )
            (base/"metadata"/f"{vid}.json").write_text(json.dumps({
                "id":vid,"title":"Metadata Title","webpage_url":f"https://www.youtube.com/watch?v={vid}",
                "channel":"Metadata Channel","channel_id":"UC_META","upload_date":"20260919"
            }),encoding="utf-8")

        out=root/"analysis"
        cp=subprocess.run([
            sys.executable,str(repo/"scripts"/"build_research_ledger.py"),
            "--research-root",str(research),"--output-dir",str(out)
        ],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,cwd=str(repo))
        if cp.returncode:
            raise RuntimeError(cp.stderr or cp.stdout)

        rows=list(csv.DictReader((out/"transcript_units.csv").open(encoding="utf-8-sig")))
        current=[r for r in rows if r.get("source_status")=="CURRENT"]
        assert current,current
        assert all(r["content_id"]=="VID_PROD" for r in current),current
        assert all(r["channel_id"]=="YT001" for r in current),current
        assert all(r["title"]=="Metadata Title" for r in current),current
        assert all(r["channel_name"]=="Metadata Channel" for r in current),current
        assert all(r["platform_channel_id"]=="UC_META" for r in current),current
        assert all(r["published_date"]=="2026-09-19" for r in current),current
        assert all(r["publication_precision"]=="DATE" for r in current),current
        joined=" ".join(r["text"] for r in current)
        assert joined.count("Welcome Catherine Austin Fitts")==1,joined
        assert joined.count("to the show today")==1,joined

        manifest=json.loads((out/"transcript_units_manifest.json").read_text(encoding="utf-8"))
        assert manifest["source_files"]==1,manifest
        print(json.dumps({
            "ok":True,
            "production_source_files":manifest["source_files"],
            "current_units":len(current),
            "published_date":current[0]["published_date"],
            "channel_id":current[0]["channel_id"],
            "test_channel_excluded":True,
            "deduplicated_text":joined,
        },indent=2))
    return 0

if __name__=="__main__":
    raise SystemExit(main())
