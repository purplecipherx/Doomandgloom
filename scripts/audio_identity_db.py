#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

SCHEMA_VERSION=1

SCHEMA=r"""
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS meta(
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS audio_assets(
  id INTEGER PRIMARY KEY,
  audio_sha256 TEXT NOT NULL UNIQUE,
  content_id TEXT,
  canonical_url TEXT,
  title TEXT,
  source_channel_id TEXT,
  source_path TEXT NOT NULL,
  vault_path TEXT,
  codec TEXT,
  bitrate_kbps REAL,
  duration_seconds REAL,
  acquired_at TEXT,
  first_seen_at TEXT NOT NULL,
  last_seen_at TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'ACTIVE'
);

CREATE TABLE IF NOT EXISTS acoustic_clusters(
  cluster_observation_id TEXT PRIMARY KEY,
  pipeline_cluster_id TEXT NOT NULL,
  channel_id TEXT,
  moji_output_path TEXT NOT NULL,
  embedding_model TEXT,
  centroid_json TEXT NOT NULL,
  member_count INTEGER NOT NULL,
  speech_seconds REAL NOT NULL,
  created_at TEXT NOT NULL,
  source_manifest_path TEXT
);
CREATE INDEX IF NOT EXISTS idx_acoustic_pipeline_cluster ON acoustic_clusters(pipeline_cluster_id);

CREATE TABLE IF NOT EXISTS cluster_sources(
  cluster_observation_id TEXT NOT NULL REFERENCES acoustic_clusters(cluster_observation_id) ON DELETE CASCADE,
  audio_sha256 TEXT,
  source_path TEXT NOT NULL,
  file_id TEXT,
  local_speaker TEXT,
  similarity REAL,
  PRIMARY KEY(cluster_observation_id,source_path,file_id,local_speaker)
);

CREATE TABLE IF NOT EXISTS canonical_speakers(
  id INTEGER PRIMARY KEY,
  canonical_voice_id TEXT UNIQUE,
  resolved_entity_id TEXT,
  display_name TEXT,
  identity_status TEXT NOT NULL DEFAULT 'UNKNOWN',
  identity_confidence REAL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  notes TEXT
);

CREATE TABLE IF NOT EXISTS speaker_bindings(
  cluster_observation_id TEXT PRIMARY KEY REFERENCES acoustic_clusters(cluster_observation_id) ON DELETE CASCADE,
  canonical_voice_id TEXT NOT NULL REFERENCES canonical_speakers(canonical_voice_id),
  binding_status TEXT NOT NULL,
  confidence REAL,
  evidence_json TEXT,
  bound_at TEXT NOT NULL,
  bound_by TEXT
);
CREATE INDEX IF NOT EXISTS idx_bindings_voice ON speaker_bindings(canonical_voice_id);

CREATE TABLE IF NOT EXISTS identity_evidence(
  evidence_id TEXT PRIMARY KEY,
  canonical_voice_id TEXT REFERENCES canonical_speakers(canonical_voice_id),
  cluster_observation_id TEXT REFERENCES acoustic_clusters(cluster_observation_id),
  evidence_type TEXT NOT NULL,
  content_id TEXT,
  start_seconds REAL,
  end_seconds REAL,
  evidence_text TEXT,
  source_id TEXT,
  weight REAL,
  status TEXT NOT NULL DEFAULT 'ACTIVE',
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS voice_match_candidates(
  candidate_id TEXT PRIMARY KEY,
  left_cluster_observation_id TEXT NOT NULL REFERENCES acoustic_clusters(cluster_observation_id) ON DELETE CASCADE,
  right_cluster_observation_id TEXT NOT NULL REFERENCES acoustic_clusters(cluster_observation_id) ON DELETE CASCADE,
  cosine_similarity REAL NOT NULL,
  same_channel INTEGER NOT NULL DEFAULT 0,
  rank_left INTEGER,
  rank_right INTEGER,
  margin_left REAL,
  margin_right REAL,
  status TEXT NOT NULL DEFAULT 'OPEN',
  created_at TEXT NOT NULL,
  review_notes TEXT
);
CREATE INDEX IF NOT EXISTS idx_voice_match_score ON voice_match_candidates(cosine_similarity DESC);

CREATE TABLE IF NOT EXISTS reference_clips(
  reference_id TEXT PRIMARY KEY,
  canonical_voice_id TEXT NOT NULL REFERENCES canonical_speakers(canonical_voice_id),
  audio_sha256 TEXT,
  source_path TEXT NOT NULL,
  start_seconds REAL NOT NULL,
  end_seconds REAL NOT NULL,
  quality_status TEXT NOT NULL,
  verification_status TEXT NOT NULL,
  source_id TEXT,
  created_at TEXT NOT NULL,
  notes TEXT
);

CREATE TABLE IF NOT EXISTS identity_events(
  id INTEGER PRIMARY KEY,
  ts TEXT NOT NULL,
  event_type TEXT NOT NULL,
  canonical_voice_id TEXT,
  cluster_observation_id TEXT,
  detail_json TEXT
);
"""

def now():
    return datetime.now(timezone.utc).isoformat()

def clean(x):
    return str(x or "").strip()

def connect(path:Path):
    path.parent.mkdir(parents=True,exist_ok=True)
    c=sqlite3.connect(path,timeout=60)
    c.row_factory=sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("PRAGMA synchronous=NORMAL")
    c.executescript(SCHEMA)
    c.execute("INSERT OR REPLACE INTO meta(key,value) VALUES('schema_version',?)",(str(SCHEMA_VERSION),))
    c.commit()
    return c

def sha256_file(path:Path):
    h=hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda:f.read(1024*1024),b""):
            h.update(chunk)
    return h.hexdigest()

def stable(prefix,*parts):
    raw="\x1f".join(clean(x) for x in parts)
    return prefix+hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24].upper()

def cosine(a,b):
    import numpy as np
    a=np.asarray(a,dtype=float); b=np.asarray(b,dtype=float)
    na=float(np.linalg.norm(a)); nb=float(np.linalg.norm(b))
    if na<=1e-12 or nb<=1e-12:return 0.0
    return float(max(-1.0,min(1.0,float(np.dot(a,b)/(na*nb)))))

def vault_copy(source:Path,vault_root:Path,digest:str):
    ext=source.suffix.lower() or ".bin"
    target=vault_root/digest[:2]/f"{digest}{ext}"
    target.parent.mkdir(parents=True,exist_ok=True)
    if target.exists():
        return target
    try:
        os.link(source,target)
    except OSError:
        shutil.copy2(source,target)
    return target

def ingest_audio_manifest(conn,manifest:Path,vault_root:Path,channel_id=""):
    count=0
    for line in manifest.read_text(encoding="utf-8",errors="replace").splitlines():
        if not line.strip():continue
        try:r=json.loads(line)
        except Exception:continue
        ap=clean(r.get("audio_path"))
        if not ap:continue
        p=Path(ap)
        if not p.is_absolute():
            p=(manifest.parent/ap).resolve()
        else:p=p.resolve()
        if not p.exists():continue
        digest=clean(r.get("sha256")) or sha256_file(p)
        vault=vault_copy(p,vault_root,digest)
        ts=now()
        conn.execute("""
          INSERT INTO audio_assets(
            audio_sha256,content_id,canonical_url,title,source_channel_id,source_path,vault_path,
            codec,bitrate_kbps,duration_seconds,acquired_at,first_seen_at,last_seen_at,status
          ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,'ACTIVE')
          ON CONFLICT(audio_sha256) DO UPDATE SET
            content_id=COALESCE(NULLIF(excluded.content_id,''),audio_assets.content_id),
            canonical_url=COALESCE(NULLIF(excluded.canonical_url,''),audio_assets.canonical_url),
            title=COALESCE(NULLIF(excluded.title,''),audio_assets.title),
            source_channel_id=COALESCE(NULLIF(excluded.source_channel_id,''),audio_assets.source_channel_id),
            source_path=excluded.source_path,
            vault_path=excluded.vault_path,
            last_seen_at=excluded.last_seen_at,
            status='ACTIVE'
        """,(
          digest,clean(r.get("video_id")),clean(r.get("url")),clean(r.get("title")),channel_id,
          str(p),str(vault),clean(r.get("final_audio_codec") or r.get("source_ext")),
          r.get("final_audio_kbps") or r.get("source_abr_kbps") or "",
          r.get("duration") or "",clean(r.get("downloaded_at")),ts,ts
        ))
        count+=1
    conn.commit()
    return count

def source_sha_lookup(conn):
    out={}
    for r in conn.execute("SELECT audio_sha256,source_path,vault_path FROM audio_assets"):
        out[str(Path(r["source_path"]).resolve())]=r["audio_sha256"]
        if r["vault_path"]:
            out[str(Path(r["vault_path"]).resolve())]=r["audio_sha256"]
    return out

def ingest_moji(conn,moji:Path,channel_id=""):
    manifest=moji/"manifests"/"global_clusters.json"
    if not manifest.exists():
        raise SystemExit(f"Missing {manifest}")
    clusters=json.loads(manifest.read_text(encoding="utf-8"))
    sha_by_path=source_sha_lookup(conn)
    created=now()
    n=0
    for c in clusters:
        pid=clean(c.get("id"))
        centroid=c.get("centroid") or []
        members=c.get("members") or []
        obs=stable("AC_",str(moji.resolve()),pid,json.dumps(sorted(
            (m.get("file_id"),m.get("local_speaker")) for m in members
        )))
        conn.execute("""
          INSERT OR REPLACE INTO acoustic_clusters(
            cluster_observation_id,pipeline_cluster_id,channel_id,moji_output_path,
            embedding_model,centroid_json,member_count,speech_seconds,created_at,source_manifest_path
          ) VALUES(?,?,?,?,?,?,?,?,?,?)
        """,(obs,pid,channel_id,str(moji.resolve()),"hbredin/wespeaker-voxceleb-resnet34-LM",
             json.dumps(centroid),len(members),float(c.get("speech_seconds") or 0),created,str(manifest.resolve())))
        for m in members:
            # Resolve original source path from local speaker/file id through Moji sqlite.
            file_id=m.get("file_id")
            local=clean(m.get("local_speaker"))
            source_path=""
            db=moji/"voice_harvester.sqlite"
            if db.exists() and file_id is not None:
                mc=sqlite3.connect(db); mc.row_factory=sqlite3.Row
                rr=mc.execute("SELECT path FROM source_files WHERE id=?",(file_id,)).fetchone()
                mc.close()
                if rr:source_path=clean(rr["path"])
            digest=sha_by_path.get(str(Path(source_path).resolve())) if source_path else ""
            conn.execute("""
              INSERT OR REPLACE INTO cluster_sources(
                cluster_observation_id,audio_sha256,source_path,file_id,local_speaker,similarity
              ) VALUES(?,?,?,?,?,?)
            """,(obs,digest,source_path,clean(file_id),local,float(m.get("similarity") or 0)))
        n+=1
    conn.commit()
    return n

def build_candidates(conn,min_similarity=0.58):
    rows=conn.execute("SELECT * FROM acoustic_clusters ORDER BY created_at,cluster_observation_id").fetchall()
    data=[]
    for r in rows:
        d=dict(r); d["centroid"]=json.loads(r["centroid_json"]); data.append(d)
    scored=defaultdict(list)
    pairs=[]
    for i,a in enumerate(data):
        for b in data[i+1:]:
            if a["cluster_observation_id"]==b["cluster_observation_id"]:continue
            sim=cosine(a["centroid"],b["centroid"])
            if sim<min_similarity:continue
            pair=(a,b,sim)
            pairs.append(pair)
            scored[a["cluster_observation_id"]].append((sim,b["cluster_observation_id"]))
            scored[b["cluster_observation_id"]].append((sim,a["cluster_observation_id"]))
    ranks={}
    margins={}
    for cid,vals in scored.items():
        vals=sorted(vals,reverse=True)
        for idx,(sim,other) in enumerate(vals,1):
            ranks[(cid,other)]=idx
        margins[cid]=(vals[0][0]-vals[1][0]) if len(vals)>1 else (vals[0][0] if vals else 0.0)
    ts=now()
    for a,b,sim in pairs:
        left=a["cluster_observation_id"]; right=b["cluster_observation_id"]
        cid=stable("VM_",*sorted((left,right)))
        conn.execute("""
          INSERT INTO voice_match_candidates(
            candidate_id,left_cluster_observation_id,right_cluster_observation_id,cosine_similarity,
            same_channel,rank_left,rank_right,margin_left,margin_right,status,created_at
          ) VALUES(?,?,?,?,?,?,?,?,?,'OPEN',?)
          ON CONFLICT(candidate_id) DO UPDATE SET
            cosine_similarity=excluded.cosine_similarity,rank_left=excluded.rank_left,rank_right=excluded.rank_right,
            margin_left=excluded.margin_left,margin_right=excluded.margin_right
        """,(cid,left,right,sim,int(clean(a.get("channel_id"))==clean(b.get("channel_id")) and clean(a.get("channel_id"))!=""),
             ranks.get((left,right)),ranks.get((right,left)),margins.get(left),margins.get(right),ts))
    conn.commit()
    return len(pairs)

def new_voice(conn,display_name="",entity_id="",status="UNKNOWN",confidence=None,notes=""):
    ts=now()
    cur=conn.execute("""
      INSERT INTO canonical_speakers(canonical_voice_id,resolved_entity_id,display_name,identity_status,identity_confidence,created_at,updated_at,notes)
      VALUES(NULL,?,?,?,?,?,?,?)
    """,(entity_id,display_name,status,confidence,ts,ts,notes))
    vid=f"VOICE_{cur.lastrowid:08d}"
    conn.execute("UPDATE canonical_speakers SET canonical_voice_id=? WHERE id=?",(vid,cur.lastrowid))
    conn.execute("INSERT INTO identity_events(ts,event_type,canonical_voice_id,detail_json) VALUES(?,?,?,?)",
                 (ts,"CANONICAL_VOICE_CREATED",vid,json.dumps({"display_name":display_name,"entity_id":entity_id})))
    conn.commit()
    return vid

def bind(conn,cluster_id,voice_id,status,confidence,evidence,bound_by):
    ts=now()
    if not conn.execute("SELECT 1 FROM acoustic_clusters WHERE cluster_observation_id=?",(cluster_id,)).fetchone():
        raise SystemExit(f"Unknown cluster: {cluster_id}")
    if not conn.execute("SELECT 1 FROM canonical_speakers WHERE canonical_voice_id=?",(voice_id,)).fetchone():
        raise SystemExit(f"Unknown voice: {voice_id}")
    conn.execute("""
      INSERT INTO speaker_bindings(cluster_observation_id,canonical_voice_id,binding_status,confidence,evidence_json,bound_at,bound_by)
      VALUES(?,?,?,?,?,?,?)
      ON CONFLICT(cluster_observation_id) DO UPDATE SET
        canonical_voice_id=excluded.canonical_voice_id,binding_status=excluded.binding_status,
        confidence=excluded.confidence,evidence_json=excluded.evidence_json,bound_at=excluded.bound_at,bound_by=excluded.bound_by
    """,(cluster_id,voice_id,status,confidence,json.dumps(evidence,ensure_ascii=False),ts,bound_by))
    conn.execute("INSERT INTO identity_events(ts,event_type,canonical_voice_id,cluster_observation_id,detail_json) VALUES(?,?,?,?,?)",
                 (ts,"CLUSTER_BOUND",voice_id,cluster_id,json.dumps({"status":status,"confidence":confidence,"evidence":evidence},ensure_ascii=False)))
    conn.commit()

def export_resolution(conn,out:Path):
    fields=["cluster_observation_id","pipeline_cluster_id","channel_id","canonical_voice_id","resolved_entity_id",
            "display_name","identity_status","binding_status","confidence","moji_output_path"]
    rows=[]
    q="""
      SELECT ac.cluster_observation_id,ac.pipeline_cluster_id,ac.channel_id,ac.moji_output_path,
             sb.canonical_voice_id,sb.binding_status,sb.confidence,
             cs.resolved_entity_id,cs.display_name,cs.identity_status
      FROM acoustic_clusters ac
      LEFT JOIN speaker_bindings sb ON sb.cluster_observation_id=ac.cluster_observation_id
      LEFT JOIN canonical_speakers cs ON cs.canonical_voice_id=sb.canonical_voice_id
      ORDER BY ac.channel_id,ac.pipeline_cluster_id
    """
    for r in conn.execute(q):rows.append(dict(r))
    out.parent.mkdir(parents=True,exist_ok=True)
    with out.open("w",newline="",encoding="utf-8-sig") as f:
        w=csv.DictWriter(f,fieldnames=fields); w.writeheader()
        for r in rows:w.writerow({k:r.get(k,"") for k in fields})
    return len(rows)

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--db",default="research/audio_identity/voice_identity.sqlite")
    sub=ap.add_subparsers(dest="cmd",required=True)

    s=sub.add_parser("init")
    s=sub.add_parser("ingest-audio"); s.add_argument("--manifest",required=True); s.add_argument("--vault",default="research/audio_vault"); s.add_argument("--channel-id",default="")
    s=sub.add_parser("ingest-moji"); s.add_argument("--moji-output",required=True); s.add_argument("--channel-id",default="")
    s=sub.add_parser("match"); s.add_argument("--min-similarity",type=float,default=0.58)
    s=sub.add_parser("new-voice"); s.add_argument("--display-name",default=""); s.add_argument("--entity-id",default=""); s.add_argument("--status",default="UNKNOWN"); s.add_argument("--confidence",type=float); s.add_argument("--notes",default="")
    s=sub.add_parser("bind"); s.add_argument("--cluster",required=True); s.add_argument("--voice",required=True); s.add_argument("--status",default="POSSIBLE"); s.add_argument("--confidence",type=float,default=0.0); s.add_argument("--evidence-json",default="{}"); s.add_argument("--bound-by",default="")
    s=sub.add_parser("export"); s.add_argument("--output",default="data/audio/speaker_resolution_current.csv")
    s=sub.add_parser("stats")

    args=ap.parse_args()
    repo=Path(__file__).resolve().parents[1]
    db=(repo/args.db).resolve() if not Path(args.db).is_absolute() else Path(args.db)
    conn=connect(db)

    if args.cmd=="init":
        print(db); return 0
    if args.cmd=="ingest-audio":
        manifest=Path(args.manifest).resolve(); vault=(repo/args.vault).resolve()
        print(json.dumps({"audio_assets_ingested":ingest_audio_manifest(conn,manifest,vault,args.channel_id)},indent=2)); return 0
    if args.cmd=="ingest-moji":
        print(json.dumps({"clusters_ingested":ingest_moji(conn,Path(args.moji_output).resolve(),args.channel_id)},indent=2)); return 0
    if args.cmd=="match":
        print(json.dumps({"match_candidates":build_candidates(conn,args.min_similarity)},indent=2)); return 0
    if args.cmd=="new-voice":
        print(new_voice(conn,args.display_name,args.entity_id,args.status,args.confidence,args.notes)); return 0
    if args.cmd=="bind":
        try:evidence=json.loads(args.evidence_json)
        except Exception:raise SystemExit("--evidence-json must be valid JSON")
        bind(conn,args.cluster,args.voice,args.status,args.confidence,evidence,args.bound_by); print("bound"); return 0
    if args.cmd=="export":
        print(json.dumps({"rows":export_resolution(conn,(repo/args.output).resolve())},indent=2)); return 0
    if args.cmd=="stats":
        stats={}
        for table in ["audio_assets","acoustic_clusters","canonical_speakers","speaker_bindings","identity_evidence","voice_match_candidates","reference_clips"]:
            stats[table]=conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        stats["open_match_candidates"]=conn.execute("SELECT COUNT(*) FROM voice_match_candidates WHERE status='OPEN'").fetchone()[0]
        print(json.dumps(stats,indent=2)); return 0

if __name__=="__main__":
    raise SystemExit(main())
