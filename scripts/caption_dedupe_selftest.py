#!/usr/bin/env python3
from __future__ import annotations

import json,tempfile
from pathlib import Path

from build_research_ledger import reconstruct_caption_segments

def main():
    cues=[
        (15.11,15.12,"Ladies and gentlemen, welcome to the"),
        (15.12,17.269,"Ladies and gentlemen, welcome to the Cari Report. We have an immense treat"),
        (17.269,17.279,"Cari Report. We have an immense treat"),
        (17.279,20.47,"Cari Report. We have an immense treat for you today. Um, Alistister Crook is,"),
        (20.47,20.48,"for you today. Um, Alistister Crook is,"),
        (20.48,22.55,"for you today. Um, Alistister Crook is, as you know from listening to Money and"),
        (22.55,22.56,"as you know from listening to Money and"),
        (22.56,24.95,"as you know from listening to Money and Markets or listening to our coverage, is"),
    ]
    with tempfile.TemporaryDirectory(prefix="doomandgloom_caption_dedupe_") as td:
        p=Path(td)/"VID.segments.jsonl"
        p.write_text("\n".join(json.dumps({"start":a,"end":b,"text":t}) for a,b,t in cues)+"\n",encoding="utf-8")
        segs,stats=reconstruct_caption_segments(p)
        text=" ".join(x["text"] for x in segs)
        assert stats["raw_cues"]==8,stats
        assert text.count("Ladies and gentlemen")==1,text
        assert text.count("Cari Report")==1,text
        assert text.count("for you today")==1,text
        assert text.count("as you know from listening to Money and")==1,text
        assert "Markets or listening to our coverage" in text,text
        raw_words=sum(len(t.split()) for _,_,t in cues)
        dedup_words=len(text.split())
        assert dedup_words < raw_words*0.65,(raw_words,dedup_words,text)
        print(json.dumps({
            "ok":True,
            "raw_cues":stats["raw_cues"],
            "raw_words":raw_words,
            "deduplicated_words":dedup_words,
            "reconstructed_segments":stats["reconstructed_segments"],
            "text":text
        },indent=2))
    return 0

if __name__=="__main__":
    raise SystemExit(main())
