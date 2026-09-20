#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sqlite3
import threading
import time
import urllib.parse
from datetime import datetime, timezone, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

def now():
    return datetime.now(timezone.utc).isoformat()

def parse_ts(s):
    try:
        return datetime.fromisoformat(s)
    except Exception:
        return datetime.now(timezone.utc)

class JobDB:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.local = threading.local()
        self.init()

    def conn(self):
        c = getattr(self.local, "conn", None)
        if c is None:
            c = sqlite3.connect(self.path, timeout=30, isolation_level=None, check_same_thread=False)
            c.row_factory = sqlite3.Row
            c.execute("PRAGMA journal_mode=WAL")
            c.execute("PRAGMA synchronous=NORMAL")
            c.execute("PRAGMA busy_timeout=30000")
            self.local.conn = c
        return c

    def init(self):
        c = sqlite3.connect(self.path)
        c.executescript("""
        PRAGMA journal_mode=WAL;
        CREATE TABLE IF NOT EXISTS jobs(
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          job_key TEXT NOT NULL UNIQUE,
          kind TEXT NOT NULL,
          lane TEXT NOT NULL,
          payload_json TEXT NOT NULL,
          priority INTEGER NOT NULL DEFAULT 100,
          state TEXT NOT NULL DEFAULT 'queued',
          attempts INTEGER NOT NULL DEFAULT 0,
          max_attempts INTEGER NOT NULL DEFAULT 3,
          available_at TEXT NOT NULL,
          lease_until TEXT,
          leased_by TEXT,
          created_at TEXT NOT NULL,
          started_at TEXT,
          completed_at TEXT,
          updated_at TEXT NOT NULL,
          last_error TEXT,
          result_json TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_jobs_sched
          ON jobs(state,lane,priority,available_at,id);
        CREATE TABLE IF NOT EXISTS job_events(
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          job_id INTEGER,
          ts TEXT NOT NULL,
          worker TEXT,
          event_type TEXT NOT NULL,
          detail_json TEXT
        );
        """)
        c.commit(); c.close()

    def event(self, job_id, event_type, worker="", detail=None):
        self.conn().execute(
            "INSERT INTO job_events(job_id,ts,worker,event_type,detail_json) VALUES(?,?,?,?,?)",
            (job_id, now(), worker, event_type, json.dumps(detail or {}, ensure_ascii=False))
        )

    def enqueue(self, kind, lane, payload, job_key, priority=100, max_attempts=3, force=False):
        c=self.conn(); ts=now()
        row=c.execute("SELECT * FROM jobs WHERE job_key=?", (job_key,)).fetchone()
        if row and not force:
            return dict(row), False
        if row and force:
            c.execute("""UPDATE jobs SET kind=?,lane=?,payload_json=?,priority=?,state='queued',
                         attempts=0,max_attempts=?,available_at=?,lease_until=NULL,leased_by=NULL,
                         started_at=NULL,completed_at=NULL,updated_at=?,last_error=NULL,result_json=NULL
                         WHERE job_key=?""",
                      (kind,lane,json.dumps(payload,ensure_ascii=False),priority,max_attempts,ts,ts,job_key))
            row=c.execute("SELECT * FROM jobs WHERE job_key=?", (job_key,)).fetchone()
            self.event(row["id"],"requeued_force",detail={"job_key":job_key})
            return dict(row), True
        cur=c.execute("""INSERT INTO jobs(job_key,kind,lane,payload_json,priority,state,attempts,max_attempts,
                         available_at,created_at,updated_at)
                         VALUES(?,?,?,?,?,'queued',0,?,?,?,?)""",
                      (job_key,kind,lane,json.dumps(payload,ensure_ascii=False),priority,max_attempts,ts,ts,ts))
        jid=cur.lastrowid
        self.event(jid,"enqueued",detail={"job_key":job_key,"kind":kind,"lane":lane})
        row=c.execute("SELECT * FROM jobs WHERE id=?", (jid,)).fetchone()
        return dict(row), True

    def reclaim_expired(self):
        c=self.conn(); ts=now()
        rows=c.execute("SELECT id,leased_by FROM jobs WHERE state='leased' AND lease_until IS NOT NULL AND lease_until<?",(ts,)).fetchall()
        for r in rows:
            c.execute("""UPDATE jobs SET state='queued',leased_by=NULL,lease_until=NULL,available_at=?,updated_at=? WHERE id=?""",(ts,ts,r["id"]))
            self.event(r["id"],"lease_expired",worker=r["leased_by"] or "")
        return len(rows)

    def lease(self, lane, worker, kinds=None, lease_seconds=900):
        c=self.conn(); self.reclaim_expired(); ts=now()
        until=(datetime.now(timezone.utc)+timedelta(seconds=max(30,int(lease_seconds)))).isoformat()
        c.execute("BEGIN IMMEDIATE")
        try:
            params=[lane,ts]
            sql="""SELECT * FROM jobs WHERE state='queued' AND lane=? AND available_at<=?"""
            if kinds:
                qs=",".join("?" for _ in kinds); sql+=f" AND kind IN ({qs})"; params.extend(kinds)
            sql+=" ORDER BY priority ASC,id ASC LIMIT 1"
            row=c.execute(sql,params).fetchone()
            if not row:
                c.execute("COMMIT"); return None
            attempts=int(row["attempts"])+1
            c.execute("""UPDATE jobs SET state='leased',attempts=?,leased_by=?,lease_until=?,
                         started_at=COALESCE(started_at,?),updated_at=? WHERE id=?""",
                      (attempts,worker,until,ts,ts,row["id"]))
            c.execute("COMMIT")
        except Exception:
            c.execute("ROLLBACK"); raise
        self.event(row["id"],"leased",worker,{"lease_until":until})
        return dict(c.execute("SELECT * FROM jobs WHERE id=?", (row["id"],)).fetchone())

    def heartbeat(self, job_id, worker, lease_seconds=900):
        until=(datetime.now(timezone.utc)+timedelta(seconds=max(30,int(lease_seconds)))).isoformat()
        cur=self.conn().execute("""UPDATE jobs SET lease_until=?,updated_at=? WHERE id=? AND state='leased' AND leased_by=?""",
                                (until,now(),job_id,worker))
        return cur.rowcount>0, until

    def complete(self, job_id, worker, result=None):
        ts=now()
        cur=self.conn().execute("""UPDATE jobs SET state='done',lease_until=NULL,completed_at=?,updated_at=?,
                                  result_json=?,last_error=NULL WHERE id=? AND state='leased' AND leased_by=?""",
                                (ts,ts,json.dumps(result or {},ensure_ascii=False),job_id,worker))
        if cur.rowcount:
            self.event(job_id,"completed",worker,result or {})
        return cur.rowcount>0

    def fail(self, job_id, worker, error, retry_delay=30):
        c=self.conn()
        row=c.execute("SELECT attempts,max_attempts FROM jobs WHERE id=?",(job_id,)).fetchone()
        if not row: return False
        retry=int(row["attempts"]) < int(row["max_attempts"])
        ts=now()
        if retry:
            avail=(datetime.now(timezone.utc)+timedelta(seconds=max(0,int(retry_delay)))).isoformat()
            c.execute("""UPDATE jobs SET state='queued',leased_by=NULL,lease_until=NULL,available_at=?,
                         updated_at=?,last_error=? WHERE id=?""",(avail,ts,str(error)[:8000],job_id))
            self.event(job_id,"retry_scheduled",worker,{"error":str(error),"available_at":avail})
        else:
            c.execute("""UPDATE jobs SET state='failed',leased_by=NULL,lease_until=NULL,completed_at=?,
                         updated_at=?,last_error=? WHERE id=?""",(ts,ts,str(error)[:8000],job_id))
            self.event(job_id,"failed",worker,{"error":str(error)})
        return True

    def stats(self):
        c=self.conn(); self.reclaim_expired()
        rows=c.execute("SELECT lane,state,COUNT(*) n FROM jobs GROUP BY lane,state ORDER BY lane,state").fetchall()
        by={}
        for r in rows:
            by.setdefault(r["lane"],{})[r["state"]]=r["n"]
        kinds=[dict(r) for r in c.execute("SELECT kind,state,COUNT(*) n FROM jobs GROUP BY kind,state ORDER BY kind,state")]
        return {"database":str(self.path),"lanes":by,"kinds":kinds,"ts":now()}

    def list_jobs(self, state=None, lane=None, kind=None, limit=100):
        sql="SELECT * FROM jobs WHERE 1=1"; params=[]
        for col,val in (("state",state),("lane",lane),("kind",kind)):
            if val: sql+=f" AND {col}=?"; params.append(val)
        sql+=" ORDER BY id DESC LIMIT ?"; params.append(max(1,min(int(limit),1000)))
        return [dict(r) for r in self.conn().execute(sql,params).fetchall()]

class API(BaseHTTPRequestHandler):
    db=None

    def log_message(self, fmt, *args):
        return

    def send_json(self, code, obj):
        data=json.dumps(obj,ensure_ascii=False).encode("utf-8")
        self.send_response(code); self.send_header("Content-Type","application/json")
        self.send_header("Content-Length",str(len(data))); self.end_headers(); self.wfile.write(data)

    def body(self):
        n=int(self.headers.get("Content-Length","0") or 0)
        return json.loads(self.rfile.read(n).decode("utf-8")) if n else {}

    def do_GET(self):
        u=urllib.parse.urlparse(self.path); q=urllib.parse.parse_qs(u.query)
        if u.path=="/health":
            return self.send_json(200,{"ok":True,"service":"doomandgloom-job-hub","ts":now()})
        if u.path=="/stats":
            return self.send_json(200,self.db.stats())
        if u.path=="/jobs":
            jobs=self.db.list_jobs(
                state=(q.get("state") or [None])[0],
                lane=(q.get("lane") or [None])[0],
                kind=(q.get("kind") or [None])[0],
                limit=(q.get("limit") or [100])[0],
            )
            return self.send_json(200,{"jobs":jobs})
        return self.send_json(404,{"error":"not found"})

    def do_POST(self):
        try: b=self.body()
        except Exception as e: return self.send_json(400,{"error":repr(e)})
        try:
            if self.path=="/enqueue":
                row,created=self.db.enqueue(
                    b["kind"],b["lane"],b.get("payload") or {},b["job_key"],
                    int(b.get("priority",100)),int(b.get("max_attempts",3)),bool(b.get("force",False))
                )
                return self.send_json(200,{"created":created,"job":row})
            if self.path=="/lease":
                row=self.db.lease(b["lane"],b["worker"],b.get("kinds"),int(b.get("lease_seconds",900)))
                return self.send_json(200,{"job":row})
            if self.path=="/heartbeat":
                ok,until=self.db.heartbeat(int(b["job_id"]),b["worker"],int(b.get("lease_seconds",900)))
                return self.send_json(200,{"ok":ok,"lease_until":until})
            if self.path=="/complete":
                ok=self.db.complete(int(b["job_id"]),b["worker"],b.get("result") or {})
                return self.send_json(200,{"ok":ok})
            if self.path=="/fail":
                ok=self.db.fail(int(b["job_id"]),b["worker"],b.get("error",""),int(b.get("retry_delay",30)))
                return self.send_json(200,{"ok":ok})
        except Exception as e:
            return self.send_json(500,{"error":repr(e)})
        return self.send_json(404,{"error":"not found"})

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("command",choices=["serve","init","stats"])
    ap.add_argument("--db",default="research/runtime/pipeline_jobs.sqlite")
    ap.add_argument("--host",default="127.0.0.1")
    ap.add_argument("--port",type=int,default=8765)
    args=ap.parse_args()
    db=JobDB(Path(args.db).resolve())
    if args.command=="init":
        print(db.path); return 0
    if args.command=="stats":
        print(json.dumps(db.stats(),indent=2)); return 0
    API.db=db
    server=ThreadingHTTPServer((args.host,args.port),API)
    print(f"Doomandgloom job hub http://{args.host}:{args.port} db={db.path}")
    try: server.serve_forever()
    except KeyboardInterrupt: pass
    finally: server.server_close()
    return 0

if __name__=="__main__":
    raise SystemExit(main())
