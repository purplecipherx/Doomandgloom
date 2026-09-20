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
import subprocess
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

SCHEMA_VERSION=3

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
  candidate_entity_id TEXT,
  candidate_name TEXT,
  content_id TEXT,
  start_seconds REAL,
  end_seconds REAL,
  evidence_text TEXT,
  source_id TEXT,
  weight REAL,
  status TEXT NOT NULL DEFAULT 'ACTIVE',
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS identity_hypotheses(
  hypothesis_id TEXT PRIMARY KEY,
  cluster_observation_id TEXT NOT NULL REFERENCES acoustic_clusters(cluster_observation_id) ON DELETE CASCADE,
  candidate_entity_id TEXT,
  candidate_name TEXT,
  context_score REAL NOT NULL DEFAULT 0,
  acoustic_score REAL NOT NULL DEFAULT 0,
  combined_score REAL NOT NULL DEFAULT 0,
  evidence_count INTEGER NOT NULL DEFAULT 0,
  independent_content_count INTEGER NOT NULL DEFAULT 0,
  direct_evidence_count INTEGER NOT NULL DEFAULT 0,
  status TEXT NOT NULL DEFAULT 'OPEN',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  notes TEXT
);
CREATE INDEX IF NOT EXISTS idx_identity_hypothesis_score ON identity_hypotheses(combined_score DESC);

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

CREATE TABLE IF NOT EXISTS voice_exemplars(
  exemplar_id TEXT PRIMARY KEY,
  cluster_observation_id TEXT NOT NULL REFERENCES acoustic_clusters(cluster_observation_id) ON DELETE CASCADE,
  canonical_voice_id TEXT REFERENCES canonical_speakers(canonical_voice_id),
  source_audio_sha256 TEXT,
  source_path TEXT NOT NULL,
  source_start REAL NOT NULL,
  source_end REAL NOT NULL,
  duration_seconds REAL NOT NULL,
  clip_path TEXT NOT NULL,
  clip_sha256 TEXT NOT NULL,
  codec TEXT,
  sample_rate INTEGER,
  quality_score REAL,
  verification_status TEXT NOT NULL DEFAULT 'UNVERIFIED',
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_exemplar_cluster ON voice_exemplars(cluster_observation_id);
CREATE INDEX IF NOT EXISTS idx_exemplar_voice ON voice_exemplars(canonical_voice_id);

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
    cols={r["name"] for r in c.execute("PRAGMA table_info(identity_evidence)")}
    if "candidate_entity_id" not in cols:
        c.execute("ALTER TABLE identity_evidence ADD COLUMN candidate_entity_id TEXT")
    if "candidate_name" not in cols:
        c.execute("ALTER TABLE identity_evidence ADD COLUMN candidate_name TEXT")
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
            candidates=[(manifest.parent/ap).resolve(),(manifest.parent.parent/ap).resolve()]
            p=next((x for x in candidates if x.exists()),candidates[0])
        else:
            p=p.resolve()
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


def extract_clip(source:Path,start:float,end:float,target:Path,sample_rate=16000):
    target.parent.mkdir(parents=True,exist_ok=True)
    duration=max(0.05,float(end)-float(start))
    cmd=[
        "ffmpeg","-hide_banner","-loglevel","error","-y",
        "-ss",f"{max(0.0,float(start)):.6f}","-i",str(source),
        "-t",f"{duration:.6f}","-vn","-ac","1","-ar",str(sample_rate),
        "-c:a","flac",str(target)
    ]
    cp=subprocess.run(cmd,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
    if cp.returncode:
        raise RuntimeError(cp.stderr.strip() or f"ffmpeg exemplar extraction failed: {source}")
    return target

def extract_exemplars(conn,moji:Path,vault_root:Path,per_local_speaker=8,min_sec=2.0,max_sec=10.0):
    import subprocess
    manifest=moji/"manifests"/"global_clusters.json"
    db=moji/"voice_harvester.sqlite"
    if not manifest.exists() or not db.exists():
        raise SystemExit(f"Missing Moji cluster manifest/database under {moji}")
    clusters=json.loads(manifest.read_text(encoding="utf-8"))
    mc=sqlite3.connect(db); mc.row_factory=sqlite3.Row
    sha_by_path=source_sha_lookup(conn)
    created=now(); count=0
    for c in clusters:
        pid=clean(c.get("id"))
        row=conn.execute(
            "SELECT cluster_observation_id FROM acoustic_clusters WHERE moji_output_path=? AND pipeline_cluster_id=? ORDER BY created_at DESC LIMIT 1",
            (str(moji.resolve()),pid)
        ).fetchone()
        if not row: continue
        obs=row["cluster_observation_id"]
        for m in c.get("members") or []:
            file_id=m.get("file_id"); local=clean(m.get("local_speaker"))
            sf=mc.execute("SELECT path FROM source_files WHERE id=?",(file_id,)).fetchone()
            if not sf: continue
            source=Path(sf["path"]).resolve()
            segs=mc.execute(
                """SELECT start,end,duration FROM segments
                   WHERE file_id=? AND local_speaker=? AND overlap=0 AND duration>=?
                   ORDER BY duration DESC,start ASC""",
                (file_id,local,float(min_sec))
            ).fetchall()
            used=0
            for seg in segs:
                if used>=int(per_local_speaker): break
                start=float(seg["start"]); end=float(seg["end"])
                if end-start>float(max_sec):
                    mid=(start+end)/2.0
                    start=max(0.0,mid-float(max_sec)/2.0)
                    end=start+float(max_sec)
                key=stable("VX_",obs,str(file_id),local,f"{start:.6f}",f"{end:.6f}")
                target=vault_root/"exemplars"/obs[:6]/obs/f"{key}.flac"
                if not target.exists():
                    extract_clip(source,start,end,target,16000)
                clip_sha=sha256_file(target)
                digest=sha_by_path.get(str(source),"")
                duration=end-start
                quality=min(1.0,max(0.0,duration/8.0))
                binding=conn.execute(
                    "SELECT canonical_voice_id,binding_status FROM speaker_bindings WHERE cluster_observation_id=?",
                    (obs,)
                ).fetchone()
                conn.execute(
                    """INSERT OR REPLACE INTO voice_exemplars(
                       exemplar_id,cluster_observation_id,canonical_voice_id,source_audio_sha256,source_path,
                       source_start,source_end,duration_seconds,clip_path,clip_sha256,codec,sample_rate,
                       quality_score,verification_status,created_at
                    ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (key,obs,binding["canonical_voice_id"] if binding else None,digest,str(source),
                     start,end,duration,str(target),clip_sha,"flac",16000,quality,
                     "BOUND_UNVERIFIED" if binding else "UNVERIFIED",created)
                )
                count+=1; used+=1
    mc.close(); conn.commit()
    return count

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


IDENTITY_EVIDENCE_WEIGHTS = {
    "SELF_IDENTIFICATION": 1.00,
    "HOST_INTRODUCTION": 0.95,
    "EXPLICIT_INTRODUCTION": 0.95,
    "CHANNEL_HOST_METADATA": 0.85,
    "DIRECT_ADDRESS": 0.70,
    "TITLE_METADATA": 0.65,
    "CO_SPEAKER_REFERENCE": 0.55,
    "TRANSCRIPT_CONTEXT": 0.45,
}

def ingest_identity_clues(conn, clues_csv:Path):
    if not clues_csv.exists():
        return 0
    count=0
    for r in csv.DictReader(clues_csv.open(encoding="utf-8-sig")):
        cluster=clean(r.get("target_acoustic_cluster_id"))
        if not cluster:
            channel=clean(r.get("channel_id"))
            raw=clean(r.get("target_raw_speaker_id"))
            if raw:
                rr=conn.execute(
                    """SELECT cluster_observation_id FROM acoustic_clusters
                       WHERE pipeline_cluster_id=? AND (?='' OR channel_id=?)
                       ORDER BY created_at DESC LIMIT 1""",
                    (raw,channel,channel)
                ).fetchone()
                if rr: cluster=rr["cluster_observation_id"]
        if not cluster:
            continue
        if not conn.execute("SELECT 1 FROM acoustic_clusters WHERE cluster_observation_id=?",(cluster,)).fetchone():
            continue
        evid=clean(r.get("identity_clue_id")) or stable(
            "IE_",cluster,r.get("unit_id"),r.get("claimed_entity_id"),r.get("claimed_name"),r.get("evidence_type")
        )
        binding=conn.execute(
            "SELECT canonical_voice_id FROM speaker_bindings WHERE cluster_observation_id=?",(cluster,)
        ).fetchone()
        weight=IDENTITY_EVIDENCE_WEIGHTS.get(clean(r.get("evidence_type")).upper(),0.35)
        try:
            conf=float(r.get("confidence") or 1.0)
        except Exception:
            conf=1.0
        weight*=max(0.0,min(1.0,conf))
        payload={
            "candidate_entity_id":clean(r.get("claimed_entity_id")),
            "candidate_name":clean(r.get("claimed_name")),
            "unit_id":clean(r.get("unit_id")),
            "channel_id":clean(r.get("channel_id")),
            "speaker_adoption":clean(r.get("speaker_adoption")),
        }
        conn.execute(
            """INSERT OR REPLACE INTO identity_evidence(
               evidence_id,canonical_voice_id,cluster_observation_id,evidence_type,candidate_entity_id,candidate_name,
               content_id,start_seconds,end_seconds,evidence_text,source_id,weight,status,created_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (evid,binding["canonical_voice_id"] if binding else None,cluster,
             clean(r.get("evidence_type")).upper(),clean(r.get("claimed_entity_id")),clean(r.get("claimed_name")),
             clean(r.get("content_id")),r.get("start_seconds") or None,r.get("end_seconds") or None,
             clean(r.get("evidence_text")),clean(r.get("unit_id")),weight,"ACTIVE",now())
        )
        conn.execute(
            "INSERT INTO identity_events(ts,event_type,canonical_voice_id,cluster_observation_id,detail_json) VALUES(?,?,?,?,?)",
            (now(),"IDENTITY_CLUE_INGESTED",binding["canonical_voice_id"] if binding else None,cluster,json.dumps(payload,ensure_ascii=False))
        )
        count+=1
    conn.commit()
    return count

def fuse_identity_hypotheses(conn):
    clues=conn.execute(
        """SELECT * FROM identity_evidence WHERE status='ACTIVE'
           AND (COALESCE(candidate_entity_id,'')<>'' OR COALESCE(candidate_name,'')<>'')"""
    ).fetchall()
    grouped=defaultdict(list)
    for r in clues:
        key=(r["cluster_observation_id"],clean(r["candidate_entity_id"]),clean(r["candidate_name"]))
        grouped[key].append(r)

    created=now(); rows=[]
    for (cluster,entity_id,name),evs in grouped.items():
        if not (entity_id or name): continue
        products=1.0
        contents=set()
        direct=0
        for e in evs:
            w=max(0.0,min(1.0,float(e["weight"] or 0)))
            products*=1.0-w
            if e["content_id"]: contents.add(e["content_id"])
            if clean(e["evidence_type"]).upper() in {"SELF_IDENTIFICATION","HOST_INTRODUCTION","EXPLICIT_INTRODUCTION"}:
                direct+=1
        context=1.0-products

        acoustic=0.0
        if entity_id:
            q=conn.execute(
                """SELECT vm.cosine_similarity,
                          CASE WHEN vm.left_cluster_observation_id=? THEN vm.right_cluster_observation_id
                               ELSE vm.left_cluster_observation_id END AS other_cluster
                   FROM voice_match_candidates vm
                   WHERE vm.left_cluster_observation_id=? OR vm.right_cluster_observation_id=?""",
                (cluster,cluster,cluster)
            ).fetchall()
            for m in q:
                br=conn.execute(
                    """SELECT cs.resolved_entity_id,sb.binding_status
                       FROM speaker_bindings sb
                       JOIN canonical_speakers cs ON cs.canonical_voice_id=sb.canonical_voice_id
                       WHERE sb.cluster_observation_id=?""",(m["other_cluster"],)
                ).fetchone()
                if br and clean(br["resolved_entity_id"])==entity_id and clean(br["binding_status"]).upper() in {"VERIFIED","HIGH_CONFIDENCE"}:
                    sim=float(m["cosine_similarity"])
                    acoustic=max(acoustic,max(0.0,min(1.0,(sim-0.55)/0.35)))

        combined=1.0-(1.0-context)*(1.0-acoustic)
        status="OPEN"
        if (context>=0.88 and acoustic>=0.70) or (context>=0.96 and len(contents)>=2 and direct>=1):
            status="HIGH_CONFIDENCE_CANDIDATE"
        elif context<0.35 and acoustic<0.35:
            status="WEAK"

        hid=stable("IH_",cluster,entity_id,name)
        old=conn.execute("SELECT status,notes,created_at FROM identity_hypotheses WHERE hypothesis_id=?",(hid,)).fetchone()
        if old and clean(old["status"]).upper() in {"VERIFIED","REJECTED","HIGH_CONFIDENCE"}:
            status=old["status"]
        conn.execute(
            """INSERT INTO identity_hypotheses(
               hypothesis_id,cluster_observation_id,candidate_entity_id,candidate_name,
               context_score,acoustic_score,combined_score,evidence_count,independent_content_count,
               direct_evidence_count,status,created_at,updated_at,notes
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(hypothesis_id) DO UPDATE SET
               context_score=excluded.context_score,acoustic_score=excluded.acoustic_score,
               combined_score=excluded.combined_score,evidence_count=excluded.evidence_count,
               independent_content_count=excluded.independent_content_count,
               direct_evidence_count=excluded.direct_evidence_count,updated_at=excluded.updated_at,
               status=CASE WHEN identity_hypotheses.status IN ('VERIFIED','REJECTED','HIGH_CONFIDENCE')
                           THEN identity_hypotheses.status ELSE excluded.status END""",
            (hid,cluster,entity_id,name,context,acoustic,combined,len(evs),len(contents),direct,status,
             old["created_at"] if old else created,created,old["notes"] if old else "")
        )
        rows.append(hid)
    conn.commit()
    return len(rows)


def approve_hypothesis(conn,hypothesis_id,status,bound_by):
    h=conn.execute("SELECT * FROM identity_hypotheses WHERE hypothesis_id=?",(hypothesis_id,)).fetchone()
    if not h: raise SystemExit(f"Unknown hypothesis: {hypothesis_id}")
    status=clean(status).upper()
    if status not in {"VERIFIED","HIGH_CONFIDENCE","REJECTED"}:
        raise SystemExit("status must be VERIFIED, HIGH_CONFIDENCE, or REJECTED")
    if status=="REJECTED":
        conn.execute("UPDATE identity_hypotheses SET status='REJECTED',updated_at=? WHERE hypothesis_id=?",(now(),hypothesis_id))
        conn.commit(); return ""
    entity_id=clean(h["candidate_entity_id"]); name=clean(h["candidate_name"])
    voice=None
    if entity_id:
        r=conn.execute(
            "SELECT canonical_voice_id FROM canonical_speakers WHERE resolved_entity_id=? ORDER BY id LIMIT 1",(entity_id,)
        ).fetchone()
        if r: voice=r["canonical_voice_id"]
    if not voice:
        voice=new_voice(conn,name,entity_id,status,float(h["combined_score"] or 0),f"Created from approved {hypothesis_id}")
    evidence={"hypothesis_id":hypothesis_id,"context_score":h["context_score"],"acoustic_score":h["acoustic_score"],"combined_score":h["combined_score"]}
    bind(conn,h["cluster_observation_id"],voice,status,float(h["combined_score"] or 0),evidence,bound_by)
    conn.execute("UPDATE canonical_speakers SET identity_status=?,identity_confidence=?,updated_at=? WHERE canonical_voice_id=?",
                 (status,float(h["combined_score"] or 0),now(),voice))
    conn.execute("UPDATE identity_hypotheses SET status=?,updated_at=? WHERE hypothesis_id=?",(status,now(),hypothesis_id))
    conn.commit()
    return voice

def export_identity_hypotheses(conn,out:Path):
    fields=[
        "hypothesis_id","cluster_observation_id","candidate_entity_id","candidate_name",
        "context_score","acoustic_score","combined_score","evidence_count","independent_content_count",
        "direct_evidence_count","status","created_at","updated_at","notes"
    ]
    rows=[dict(r) for r in conn.execute(
        "SELECT * FROM identity_hypotheses ORDER BY combined_score DESC,evidence_count DESC,hypothesis_id"
    )]
    out.parent.mkdir(parents=True,exist_ok=True)
    with out.open("w",newline="",encoding="utf-8-sig") as f:
        w=csv.DictWriter(f,fieldnames=fields); w.writeheader(); w.writerows(rows)
    return len(rows)

def export_voice_match_candidates(conn,out:Path):
    fields=[
        "candidate_id","left_cluster_observation_id","right_cluster_observation_id","cosine_similarity",
        "same_channel","rank_left","rank_right","margin_left","margin_right","status","created_at","review_notes"
    ]
    rows=[dict(r) for r in conn.execute(
        "SELECT * FROM voice_match_candidates ORDER BY cosine_similarity DESC,candidate_id"
    )]
    out.parent.mkdir(parents=True,exist_ok=True)
    with out.open("w",newline="",encoding="utf-8-sig") as f:
        w=csv.DictWriter(f,fieldnames=fields); w.writeheader(); w.writerows(rows)
    return len(rows)

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--db",default="research/audio_identity/voice_identity.sqlite")
    sub=ap.add_subparsers(dest="cmd",required=True)

    s=sub.add_parser("init")
    s=sub.add_parser("ingest-audio"); s.add_argument("--manifest",required=True); s.add_argument("--vault",default="research/audio_vault"); s.add_argument("--channel-id",default="")
    s=sub.add_parser("ingest-moji"); s.add_argument("--moji-output",required=True); s.add_argument("--channel-id",default="")
    s=sub.add_parser("extract-exemplars"); s.add_argument("--moji-output",required=True); s.add_argument("--vault",default="research/audio_vault"); s.add_argument("--per-local-speaker",type=int,default=8); s.add_argument("--min-sec",type=float,default=2.0); s.add_argument("--max-sec",type=float,default=10.0)
    s=sub.add_parser("match"); s.add_argument("--min-similarity",type=float,default=0.58)
    s=sub.add_parser("ingest-clues"); s.add_argument("--clues-csv",required=True)
    s=sub.add_parser("fuse-identities")
    s=sub.add_parser("approve-hypothesis"); s.add_argument("--hypothesis",required=True); s.add_argument("--status",required=True); s.add_argument("--bound-by",default="")
    s=sub.add_parser("export-hypotheses"); s.add_argument("--output",default="data/audio/identity_hypotheses.csv")
    s=sub.add_parser("export-matches"); s.add_argument("--output",default="data/audio/voice_match_candidates.csv")
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
    if args.cmd=="extract-exemplars":
        print(json.dumps({"voice_exemplars":extract_exemplars(conn,Path(args.moji_output).resolve(),(repo/args.vault).resolve(),args.per_local_speaker,args.min_sec,args.max_sec)},indent=2)); return 0
    if args.cmd=="match":
        print(json.dumps({"match_candidates":build_candidates(conn,args.min_similarity)},indent=2)); return 0
    if args.cmd=="ingest-clues":
        print(json.dumps({"identity_clues_ingested":ingest_identity_clues(conn,Path(args.clues_csv).resolve())},indent=2)); return 0
    if args.cmd=="fuse-identities":
        print(json.dumps({"identity_hypotheses_updated":fuse_identity_hypotheses(conn)},indent=2)); return 0
    if args.cmd=="approve-hypothesis":
        print(approve_hypothesis(conn,args.hypothesis,args.status,args.bound_by)); return 0
    if args.cmd=="export-hypotheses":
        print(json.dumps({"rows":export_identity_hypotheses(conn,(repo/args.output).resolve())},indent=2)); return 0
    if args.cmd=="export-matches":
        print(json.dumps({"rows":export_voice_match_candidates(conn,(repo/args.output).resolve())},indent=2)); return 0
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
        for table in ["audio_assets","acoustic_clusters","canonical_speakers","speaker_bindings","identity_evidence","identity_hypotheses","voice_match_candidates","voice_exemplars","reference_clips"]:
            stats[table]=conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        stats["open_match_candidates"]=conn.execute("SELECT COUNT(*) FROM voice_match_candidates WHERE status='OPEN'").fetchone()[0]
        print(json.dumps(stats,indent=2)); return 0

if __name__=="__main__":
    raise SystemExit(main())
