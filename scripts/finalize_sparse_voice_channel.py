#!/usr/bin/env python3
from __future__ import annotations
import argparse, csv, json
from pathlib import Path

def main():
    ap=argparse.ArgumentParser(description="Merge sparse voice attribution batches for one channel generation.")
    ap.add_argument("--batch-root",required=True)
    ap.add_argument("--output",required=True)
    args=ap.parse_args()
    root=Path(args.batch_root).resolve(); out=Path(args.output).resolve(); out.mkdir(parents=True,exist_ok=True)
    rows=[]; batch_files=[]
    for p in sorted(root.glob("VB*/attribution/caption_speaker_attribution.csv")):
        batch_files.append(str(p))
        rows.extend(csv.DictReader(p.open(encoding="utf-8-sig")))
    rows.sort(key=lambda r:(r.get("video_id",""),float(r.get("start_seconds") or 0),int(r.get("cue_index") or 0)))
    if rows:
        fields=list(rows[0].keys())
    else:
        fields=[]
    csv_path=out/"caption_speaker_attribution.csv"
    if fields:
        with csv_path.open("w",newline="",encoding="utf-8-sig") as f:
            w=csv.DictWriter(f,fieldnames=fields); w.writeheader(); w.writerows(rows)
    else:
        csv_path.write_text("",encoding="utf-8")
    jl=out/"caption_speaker_attribution.jsonl"
    with jl.open("w",encoding="utf-8") as f:
        for r in rows:f.write(json.dumps(r,ensure_ascii=False)+"\n")
    status={}
    for r in rows:
        k=r.get("speaker_attribution_status","")
        status[k]=status.get(k,0)+1
    summary={"batch_root":str(root),"batch_files":batch_files,"batch_count":len(batch_files),
             "row_count":len(rows),"status_counts":status,"csv":str(csv_path),"jsonl":str(jl)}
    (out/"caption_speaker_attribution_manifest.json").write_text(json.dumps(summary,indent=2),encoding="utf-8")
    print(json.dumps(summary,indent=2))
    return 0
if __name__=="__main__":
    raise SystemExit(main())
