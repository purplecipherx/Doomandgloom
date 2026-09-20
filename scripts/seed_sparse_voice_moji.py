#!/usr/bin/env python3
from __future__ import annotations
import argparse, sqlite3
from pathlib import Path

def main():
    ap=argparse.ArgumentParser(description="Seed Moji speaker rows by treating each sparse clip as one speaker observation.")
    ap.add_argument("--moji-output",required=True)
    args=ap.parse_args()
    out=Path(args.moji_output).resolve(); db=out/"voice_harvester.sqlite"
    if not db.exists(): raise SystemExit(f"Missing {db}")
    c=sqlite3.connect(db,timeout=60); c.row_factory=sqlite3.Row
    c.execute("PRAGMA foreign_keys=ON")
    rows=c.execute("SELECT id,duration,scan_error FROM source_files ORDER BY id").fetchall()
    seeded=0
    with c:
        for r in rows:
            if r["scan_error"] is not None: continue
            dur=float(r["duration"] or 0)
            if dur<1.5: continue
            fid=int(r["id"])
            c.execute("DELETE FROM segments WHERE file_id=?",(fid,))
            c.execute("DELETE FROM local_speakers WHERE file_id=?",(fid,))
            c.execute(
                "INSERT INTO segments(file_id,local_speaker,start,end,duration,overlap) VALUES(?,?,?,?,?,0)",
                (fid,"SPARSE_SAMPLE",0.0,dur,dur)
            )
            c.execute(
                """INSERT INTO local_speakers(file_id,local_speaker,segment_count,speech_seconds,clean_seconds)
                   VALUES(?,?,?,?,?)""",(fid,"SPARSE_SAMPLE",1,dur,dur)
            )
            c.execute("UPDATE source_files SET diarized_at=CURRENT_TIMESTAMP,updated_at=CURRENT_TIMESTAMP WHERE id=?",(fid,))
            seeded+=1
    c.close()
    print(f"Seeded {seeded} sparse clip speaker observation(s) -> {db}")
    return 0

if __name__=="__main__":
    raise SystemExit(main())
