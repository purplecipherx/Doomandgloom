#!/usr/bin/env python3
from __future__ import annotations

import argparse, csv, hashlib, html, json, re, subprocess, sys, time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

COOKIE_BROWSER=""
SLEEP_REQUESTS=1.5
SLEEP_INTERVAL=2.0
MAX_SLEEP_INTERVAL=5.0
REMOTE_EJS=True

TS_RE=re.compile(r"(?P<s>\d{2}:\d{2}:\d{2}[.,]\d{3})\s+-->\s+(?P<e>\d{2}:\d{2}:\d{2}[.,]\d{3})")
TAG_RE=re.compile(r"<[^>]+>")
SPACE_RE=re.compile(r"\s+")

def common_ytdlp_args():
    args=[
        "--sleep-requests",str(SLEEP_REQUESTS),
        "--sleep-interval",str(SLEEP_INTERVAL),
        "--max-sleep-interval",str(MAX_SLEEP_INTERVAL),
    ]
    if REMOTE_EJS:
        args += ["--remote-components","ejs:npm"]
    if COOKIE_BROWSER:
        args += ["--cookies-from-browser",COOKIE_BROWSER]
    return args

def now(): return datetime.now(timezone.utc).isoformat()

def tool_version():
    p=ytdlp(["--version"],30)
    return p.stdout.strip() if p.returncode==0 else "unknown"

def git_commit():
    try:
        p=subprocess.run(["git","rev-parse","HEAD"],text=True,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,timeout=10)
        return p.stdout.strip() if p.returncode==0 else ""
    except Exception:
        return ""

def ytdlp(args,timeout=180):
    return subprocess.run([sys.executable,"-m","yt_dlp",*common_ytdlp_args(),*args],text=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE,encoding="utf-8",errors="replace",timeout=timeout)

def check_ytdlp():
    p=ytdlp(["--version"],30)
    if p.returncode: raise SystemExit("yt-dlp missing. Run: python -m pip install -U yt-dlp")
    print("yt-dlp",p.stdout.strip(),flush=True)

def normalize_root(url):
    u=url.strip().rstrip("/"); p=urlsplit(u)
    if "youtube.com" not in p.netloc.lower(): return u,False
    path=p.path.rstrip("/")
    for s in ("/videos","/shorts","/streams","/featured"):
        if path.endswith(s): path=path[:-len(s)]; break
    if path in ("/watch","/playlist") or "list=" in p.query: return u,False
    root=urlunsplit((p.scheme or "https",p.netloc,path,"",""))
    return root.rstrip("/"),path.startswith(("/@","/channel/","/c/","/user/"))

def sources(url):
    root,ch=normalize_root(url)
    return [("videos",root+"/videos"),("shorts",root+"/shorts"),("streams",root+"/streams")] if ch else [("input",root)]

def inventory_one(tab,url):
    print(f"[inventory] {tab}: {url}",flush=True)
    p=ytdlp(["--flat-playlist","--dump-json","--ignore-errors","--no-warnings",url],600); rows=[]
    for line in p.stdout.splitlines():
        try: o=json.loads(line)
        except Exception: continue
        if o.get("id"): o["_tab"]=tab; rows.append(o)
    print(f"[inventory] {tab}: {len(rows)}",flush=True); return rows

def merge_inventory(groups):
    d={}
    for g in groups:
        for e in g:
            vid=e["id"]
            if vid not in d:
                d[vid]={"video_id":vid,"url":f"https://www.youtube.com/watch?v={vid}","title":e.get("title") or "","channel_id":e.get("channel_id") or e.get("uploader_id") or "","channel_name":e.get("channel") or e.get("uploader") or "","duration_seconds":e.get("duration") or "","live_status":e.get("live_status") or "","tabs":set()}
            d[vid]["tabs"].add(e.get("_tab",""))
    out=[]
    for r in d.values(): r["tabs"]=";".join(sorted(x for x in r["tabs"] if x)); out.append(r)
    return out

def write_inventory(base,rows,input_url):
    base.mkdir(parents=True,exist_ok=True); fields=["video_id","url","title","channel_id","channel_name","duration_seconds","live_status","tabs"]
    with (base/"inventory.csv").open("w",newline="",encoding="utf-8-sig") as f:
        w=csv.DictWriter(f,fieldnames=fields); w.writeheader()
        for r in rows: w.writerow({k:r.get(k,"") for k in fields})
    with (base/"inventory.jsonl").open("w",encoding="utf-8") as f:
        for r in rows: f.write(json.dumps(r,ensure_ascii=False)+"\n")
    (base/"inventory_summary.json").write_text(json.dumps({"input_url":input_url,"inventoried_at":now(),"video_count":len(rows)},indent=2),encoding="utf-8")

def get_meta(url):
    p=ytdlp(["--skip-download","--dump-single-json","--ignore-errors","--no-warnings",url],240)
    if not p.stdout.strip(): return None,p.stderr.strip()
    try: return json.loads(p.stdout),p.stderr.strip()
    except Exception: return None,p.stderr.strip()

def match_lang(keys,pattern):
    rx=re.compile(pattern,re.I); return [k for k in keys if rx.fullmatch(k) or rx.search(k)]

def choose_caption(meta,pattern):
    manual=meta.get("subtitles") or {}; auto=meta.get("automatic_captions") or {}
    m=match_lang(manual.keys(),pattern)
    if m: m.sort(key=lambda x:(0 if x.lower()=="en" else 1,len(x),x)); return "manual",m[0]
    a=match_lang(auto.keys(),pattern)
    if a: a.sort(key=lambda x:(0 if x.lower()=="en" else 1,len(x),x)); return "auto",a[0]
    return None

def download_caption(url,vid,kind,lang,base):
    vdir=base/"captions"/vid; vdir.mkdir(parents=True,exist_ok=True)
    args=["--skip-download","--sub-format","vtt/best","--sub-langs",lang,"-o",str(vdir/"%(id)s.%(ext)s"),"--ignore-errors","--no-warnings"]
    args += ["--write-subs","--no-write-auto-subs"] if kind=="manual" else ["--write-auto-subs","--no-write-subs"]
    p=ytdlp([*args,url],240); files=sorted(vdir.glob(f"{vid}*.vtt"),key=lambda x:x.stat().st_mtime,reverse=True)
    return (files[0] if files else None),p.stderr.strip()

def sec(ts):
    h,m,s=ts.replace(",",".").split(":"); return int(h)*3600+int(m)*60+float(s)

def clean(s): return SPACE_RE.sub(" ",html.unescape(TAG_RE.sub("",s))).strip()

def parse_vtt(path):
    lines=path.read_text(encoding="utf-8",errors="replace").splitlines(); cues=[]; i=0
    while i<len(lines):
        m=TS_RE.search(lines[i])
        if not m: i+=1; continue
        start,end=sec(m.group("s")),sec(m.group("e")); i+=1; buf=[]
        while i<len(lines) and lines[i].strip(): buf.append(lines[i]); i+=1
        text=clean(" ".join(buf))
        if text:
            if cues and cues[-1]["text"]==text: cues[-1]["end"]=max(cues[-1]["end"],end)
            else: cues.append({"start":start,"end":end,"text":text})
        i+=1
    return cues

def overlap(prev,cur):
    a,b=prev.split(),cur.split()
    for n in range(min(30,len(a),len(b)),0,-1):
        if [x.lower() for x in a[-n:]]==[x.lower() for x in b[:n]]: return " ".join(b[n:])
    return cur

def normalize_caption(vtt,vid,base):
    cues=parse_vtt(vtt); nd=base/"normalized"; nd.mkdir(parents=True,exist_ok=True)
    seg=nd/f"{vid}.segments.jsonl"; txt=nd/f"{vid}.txt"
    with seg.open("w",encoding="utf-8") as f:
        for c in cues: f.write(json.dumps(c,ensure_ascii=False)+"\n")
    parts=[]; prev=""
    for c in cues:
        piece=overlap(prev,c["text"])
        if piece: parts.append(piece)
        prev=c["text"]
    txt.write_text(" ".join(parts).strip()+"\n",encoding="utf-8")
    return seg,txt,hashlib.sha256(vtt.read_bytes()).hexdigest()

def process(row,base,pattern,delay):
    vid,url=row["video_id"],row["url"]; rd=base/"results"; rd.mkdir(parents=True,exist_ok=True); rf=rd/f"{vid}.json"
    if rf.exists():
        try: return json.loads(rf.read_text(encoding="utf-8"))
        except Exception: pass
    if delay: time.sleep(delay)
    meta,err=get_meta(url)
    r={"video_id":vid,"url":url,"title":row.get("title",""),"channel_name":row.get("channel_name",""),"processed_at":now(),"status":"","caption_kind":"","caption_language":"","text_path":"","error":""}
    if not meta:
        r["status"]="metadata_failed"; r["error"]=err[-1000:]; rf.write_text(json.dumps(r,indent=2),encoding="utf-8"); return r
    md=base/"metadata"; md.mkdir(parents=True,exist_ok=True); (md/f"{vid}.json").write_text(json.dumps(meta,ensure_ascii=False,indent=2),encoding="utf-8")
    r["title"]=meta.get("title") or r["title"]; r["channel_name"]=meta.get("channel") or meta.get("uploader") or r["channel_name"]
    chosen=choose_caption(meta,pattern)
    if not chosen:
        r["status"]="needs_transcription"; rf.write_text(json.dumps(r,indent=2),encoding="utf-8"); return r
    kind,lang=chosen; vtt,derr=download_caption(url,vid,kind,lang,base)
    if not vtt: r["status"]="caption_download_failed"; r["error"]=derr[-1000:]
    else:
        seg,txt,sha=normalize_caption(vtt,vid,base); r.update({"status":"captioned","caption_kind":kind,"caption_language":lang,"text_path":str(txt.relative_to(base)),"segments_path":str(seg.relative_to(base)),"vtt_path":str(vtt.relative_to(base)),"sha256":sha})
    rf.write_text(json.dumps(r,indent=2),encoding="utf-8"); return r

def write_status(base,results):
    fields=["video_id","url","title","channel_name","status","caption_kind","caption_language","text_path","processed_at","error"]
    with (base/"caption_status.csv").open("w",newline="",encoding="utf-8-sig") as f:
        w=csv.DictWriter(f,fieldnames=fields); w.writeheader()
        for r in sorted(results,key=lambda x:x["video_id"]): w.writerow({k:r.get(k,"") for k in fields})
    with (base/"needs_transcription.csv").open("w",newline="",encoding="utf-8-sig") as f:
        fields2=["video_id","url","title","channel_name","reason"]; w=csv.DictWriter(f,fieldnames=fields2); w.writeheader()
        for r in results:
            if r.get("status")=="needs_transcription":
                w.writerow({"video_id":r.get("video_id",""),"url":r.get("url",""),"title":r.get("title",""),"channel_name":r.get("channel_name",""),"reason":r.get("status","")})
    with (base/"acquisition_failures.csv").open("w",newline="",encoding="utf-8-sig") as f:
        fields3=["video_id","url","title","channel_name","status","error"]; w=csv.DictWriter(f,fieldnames=fields3); w.writeheader()
        for r in results:
            if r.get("status") in {"metadata_failed","caption_download_failed","exception"}:
                w.writerow({k:r.get(k,"") for k in fields3})

def main():
    ap=argparse.ArgumentParser(description="Inventory a YouTube channel and harvest existing captions without downloading media.")
    ap.add_argument("url"); ap.add_argument("--output",default="research/youtube"); ap.add_argument("--name",default="")
    ap.add_argument("--language-regex",default=r"en(?:[-_].*)?"); ap.add_argument("--inventory-only",action="store_true")
    ap.add_argument("--workers",type=int,default=8); ap.add_argument("--sleep",type=float,default=0.75); ap.add_argument("--limit",type=int,default=0)
    ap.add_argument("--cookies-from-browser",default="")
    ap.add_argument("--sleep-requests",type=float,default=1.5)
    ap.add_argument("--sleep-interval",type=float,default=2.0)
    ap.add_argument("--max-sleep-interval",type=float,default=5.0)
    ap.add_argument("--no-remote-ejs",action="store_true")
    a=ap.parse_args()
    global COOKIE_BROWSER,SLEEP_REQUESTS,SLEEP_INTERVAL,MAX_SLEEP_INTERVAL,REMOTE_EJS
    COOKIE_BROWSER=a.cookies_from_browser.strip()
    SLEEP_REQUESTS=max(0.0,a.sleep_requests)
    SLEEP_INTERVAL=max(0.0,a.sleep_interval)
    MAX_SLEEP_INTERVAL=max(SLEEP_INTERVAL,a.max_sleep_interval)
    REMOTE_EJS=not a.no_remote_ejs
    check_ytdlp()
    srcs=sources(a.url)
    if len(srcs)>1:
        with ThreadPoolExecutor(max_workers=min(3,len(srcs))) as inv_ex:
            inv_futs=[inv_ex.submit(inventory_one,t,u) for t,u in srcs]
            inventory_groups=[f.result() for f in inv_futs]
    else:
        inventory_groups=[inventory_one(*srcs[0])]
    rows=merge_inventory(inventory_groups)
    if a.limit>0: rows=rows[:a.limit]
    root,_=normalize_root(a.url); name=a.name.strip() or re.sub(r"[^A-Za-z0-9._-]+","_",root.rstrip("/").split("/")[-1] or "youtube")
    base=Path(a.output).expanduser().resolve()/name; write_inventory(base,rows,a.url)
    manifest={
        "run_id": datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")+"_"+name,
        "started_at": now(),
        "input_url": a.url,
        "source_name": name,
        "mode": "inventory_only" if a.inventory_only else "inventory_and_captions",
        "python_version": sys.version,
        "yt_dlp_version": tool_version(),
        "repo_git_commit": git_commit(),
        "argv": sys.argv,
        "workers": a.workers,
        "sleep_seconds": a.sleep,
        "cookies_from_browser": COOKIE_BROWSER,
        "sleep_requests": SLEEP_REQUESTS,
        "sleep_interval": SLEEP_INTERVAL,
        "max_sleep_interval": MAX_SLEEP_INTERVAL,
        "remote_ejs": REMOTE_EJS,
        "language_regex": a.language_regex,
        "limit": a.limit,
        "inventory_count": len(rows)
    }
    (base/"run_manifest.json").write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding="utf-8")
    print(f"[inventory-complete] {len(rows)} unique videos -> {base/'inventory.csv'}",flush=True)
    if a.inventory_only:
        manifest["completed_at"]=now()
        manifest["status"]="complete"
        (base/"run_manifest.json").write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding="utf-8")
        return 0
    results=[]; workers=max(1,a.workers)
    with ThreadPoolExecutor(max_workers=workers) as ex:
        fs={ex.submit(process,r,base,a.language_regex,a.sleep):r["video_id"] for r in rows}; done=0
        for fut in as_completed(fs):
            try: results.append(fut.result())
            except Exception as e:
                vid=fs[fut]; results.append({"video_id":vid,"url":f"https://www.youtube.com/watch?v={vid}","title":"","channel_name":"","status":"exception","error":repr(e)})
            done+=1
            if done%10==0 or done==len(rows): print(f"[captions] {done}/{len(rows)}",flush=True)
    write_status(base,results)
    counts={}
    for r in results:
        counts[r.get("status","unknown")]=counts.get(r.get("status","unknown"),0)+1
    manifest["completed_at"]=now()
    manifest["status"]="complete"
    manifest["result_counts"]=counts
    manifest["output_files"]=["inventory.csv","inventory.jsonl","inventory_summary.json","caption_status.csv","needs_transcription.csv","acquisition_failures.csv"]
    (base/"run_manifest.json").write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding="utf-8")
    print(f"[done] {base/'caption_status.csv'}",flush=True)
    print(f"[queue] {base/'needs_transcription.csv'}",flush=True)
    return 0

if __name__=="__main__": raise SystemExit(main())
