import json,sqlite3
from pathlib import Path
from datetime import datetime,timezone

def utc():return datetime.now(timezone.utc).isoformat()
class Store:
    def __init__(self,root):
        self.root=Path(root);self.root.mkdir(parents=True,exist_ok=True)
        self.db=sqlite3.connect(self.root/'metadata.sqlite3',check_same_thread=False)
        self.db.executescript('CREATE TABLE IF NOT EXISTS probe_sessions (id TEXT PRIMARY KEY, metadata TEXT); CREATE TABLE IF NOT EXISTS events (at TEXT, kind TEXT, detail TEXT);')
    def event(self,kind,detail):
        self.db.execute('INSERT INTO events VALUES (?,?,?)',(utc(),kind,json.dumps(detail,ensure_ascii=False)));self.db.commit()
    def save(self,meta):
        self.db.execute('INSERT OR REPLACE INTO probe_sessions VALUES (?,?)',(meta['id'],json.dumps(meta,ensure_ascii=False)));self.db.commit()
    def close(self):self.db.close()
