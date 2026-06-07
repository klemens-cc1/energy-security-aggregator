"""Quick status check — run: python status.py"""
import json, os, sys, sqlite3
from pathlib import Path

ROOT = Path(__file__).parent
DB   = ROOT / "legiscan.db"

def get_conn():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    return conn

with get_conn() as c:
    total   = c.execute("SELECT COUNT(*) FROM queue").fetchone()[0]
    passed  = c.execute("SELECT COUNT(*) FROM queue q JOIN bills b ON q.bill_id=b.bill_id WHERE b.status_id IN (4,7,8)").fetchone()[0]
    failed  = c.execute("SELECT COUNT(*) FROM queue q JOIN bills b ON q.bill_id=b.bill_id WHERE b.status_id IN (5,6,11)").fetchone()[0]
    active  = total - passed - failed

cache_file = ROOT / ".dc_classify_cache.json"
if cache_file.exists():
    cache = json.loads(cache_file.read_text(encoding="utf-8"))
    classified  = len(cache)
    has_mech    = sum(1 for v in cache.values() if v.get("key_mechanism"))
    dirs = {}
    for v in cache.values():
        d = v.get("policy_direction","?")
        dirs[d] = dirs.get(d, 0) + 1
else:
    classified = has_mech = 0
    dirs = {}

pct = 100 * classified // total if total else 0

print(f"""
=== Pipeline Status ===
Queue:       {total:,} bills  ({passed} passed / {failed} failed / {active} active/unknown)

Classification:
  Cached:    {classified:,} / {total:,}  ({pct}%)
  With mechanism: {has_mech:,}
  Direction: pro={dirs.get('pro',0)}  restrictive={dirs.get('restrictive',0)}  neutral={dirs.get('neutral',0)}

Run 'python analyze_dc_bills.py' when cache reaches ~100%
""")
