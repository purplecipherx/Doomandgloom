#!/usr/bin/env python3
from __future__ import annotations

from transcript_spider import extract_mentions, candidate_eligible, classify

def curated(text):
    rows=[]
    for key,raw,typ,start,end,canonical,signal in extract_mentions(text,{}):
        ctx=text[max(0,start-120):min(len(text),end+120)]
        typ=typ or classify(raw,ctx)
        signals={signal}
        if candidate_eligible(canonical,raw,typ,1,1,signals):
            rows.append(raw)
    return rows

def assert_absent(text,*names):
    got=curated(text)
    low={x.lower() for x in got}
    for n in names:
        assert n.lower() not in low,(text,n,got)

def assert_present(text,*names):
    got=curated(text)
    low={x.lower() for x in got}
    for n in names:
        assert n.lower() in low,(text,n,got)

def main():
    assert_absent("I'm not saying that. Right. And you should see what happens.","I'm","Right. And")
    assert_absent("That's the good news. It's the whole problem.","That's the","It's the")
    assert_absent("She's got a website in Arizona where she talks about it.","in Arizona")
    assert_absent("There was a conference taking place in Beijing when we arrived.","taking place in Beijing")
    assert_present("At the end of your interview with Tucker Carlson, you discussed it.","Tucker Carlson")
    assert_present("And this is not a slam on Ron DeSantis. I disagree on this issue.","Ron DeSantis")
    assert_present("I first went to Texas and founded a company called Anaconda after that.","Anaconda")
    assert_present("We saw the same issue at Wells Fargo and Mayo Clinic.","Wells Fargo","Mayo Clinic")
    print("spider_precision_selftest=ok")
    return 0

if __name__=="__main__":
    raise SystemExit(main())
