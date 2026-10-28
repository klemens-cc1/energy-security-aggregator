"""Run: python test_pipeline.py"""
from filter import categorize


def cats(title, match_text=""):
    return categorize({"title": title, "match_text": match_text})


# Substring false positives that whole-word matching fixes
assert cats("Hindutva Goons Unleash Violence on Anti-Modi Protesters") == []
assert cats("Microsoft patches Windows 11 bug") == []
assert cats("Windfall tax debate returns") == []
assert cats("Philanthropic giving hits record") == []
assert cats("New computer chip unveiled") == []
assert "Renewables" not in cats("Hydrogen hub funding announced")
assert cats("Fed cuts rates by 50 bps") == []

# Real matches, including plurals
assert cats("TVA board approves new gas plant") == ["Georgia & Southeast US"]
assert cats("Data centers strain the grid") == ["AI & Data Centers"]
assert cats("Renewables outpace coal") == ["Renewables"]
assert cats("Two SMRs licensed in Ontario") == ["Nuclear"]
assert cats("Radiant microreactor selected by US Navy") == ["Nuclear"]
assert cats("BP cuts dividend") == ["Hydrocarbons"]
assert cats("ExxonMobil posts record profit") == ["Hydrocarbons"]
assert cats("Rooftop PV installs climb") == ["Renewables"]

# Email newsletters match on the body
assert cats("Axios Generate: Tuesday") == []
assert "AI & Data Centers" in cats("Axios Generate: Tuesday", "PJM says data center load is rising")


# Google News feeds: strip " - Publisher" from titles; topic feeds credit the outlet
import os, tempfile
os.environ["DB_PATH"] = os.path.join(tempfile.mkdtemp(), "test.db")
import feedparser
import aggregator
from db import get_conn, init_db

init_db()
_atom = """<?xml version="1.0"?><rss version="2.0"><channel><title>t</title>
<item><title>Qatar agrees to buy US LNG - Bloomberg.com</title><link>https://news.google.com/rss/articles/abc</link>
<guid>gn-1</guid><source url="https://www.bloomberg.com">Bloomberg.com</source></item></channel></rss>"""
_parse = feedparser.parse
aggregator.feedparser.parse = lambda *a, **k: _parse(_atom)
GN = "https://news.google.com/rss/search?q=LNG"
topic, _ = aggregator.fetch_feed({"name": "Google News: LNG & Gas", "url": GN})
assert [(a["title"], a["feed_name"]) for a in topic] == [("Qatar agrees to buy US LNG", "Bloomberg.com")]
with get_conn() as conn:  # fresh "seen" state for the second feed
    conn.execute("DELETE FROM articles")
site, _ = aggregator.fetch_feed({"name": "CSIS Analysis", "url": GN})
assert [(a["title"], a["feed_name"]) for a in site] == [("Qatar agrees to buy US LNG", "CSIS Analysis")]

# Category caps: max 40 per category, no source above 35% of what's kept, newest first
from collections import Counter
from filter import cap_category


def arts(spec):  # {"source": count} -> articles with distinct, descending dates
    out, i = [], 0
    for src, n in spec.items():
        for _ in range(n):
            out.append({"feed_name": src, "published_at": f"2026-10-{28 - i % 28:02d}T{i % 24:02d}:00:00+00:00"})
            i += 1
    return out


def share_ok(kept):
    return max(Counter(a["feed_name"] for a in kept).values()) <= 0.35 * len(kept)


k = cap_category(arts({f"s{i}": 5 for i in range(20)}))          # plenty of sources
assert len(k) == 40 and share_ok(k)
k = cap_category(arts({"Reuters": 40, "WSJ": 10, "FT": 10}))      # one dominant source
assert len(k) == 30 and share_ok(k)
k = cap_category(arts({"GPB": 5}))                                # single source keeps 1
assert len(k) == 1
newest = cap_category([{"feed_name": "x", "published_at": "2026-10-01"}, {"feed_name": "x", "published_at": "2026-10-20"}])
assert newest[0]["published_at"] == "2026-10-20"

# Topic categories outrank Georgia & Southeast US (regional relevance comes from the AI flag)
from filter import CATEGORY_SPECIFICITY
pick = lambda title: next(c for c in CATEGORY_SPECIFICITY if c in cats(title))
assert pick("Georgia Power data center deal") == "AI & Data Centers"
assert pick("Georgia PSC approves Georgia Power rate case") == "Georgia & Southeast US"

# AI tag responses: duplicates, out-of-range and malformed items are ignored, not trusted
import json as _json
from types import SimpleNamespace
from filter import _tag_batch


class FakeClient:
    def __init__(self, items):
        msg = SimpleNamespace(content=_json.dumps({"items": items}))
        create = lambda **kw: SimpleNamespace(choices=[SimpleNamespace(message=msg)])
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=create))


batch = [{"title": "a"}, {"title": "b"}, {"title": "c"}]
_tag_batch(FakeClient([
    {"n": 1, "score": 8, "southeast": True},
    {"n": 1, "score": 10, "southeast": False},   # duplicate: ignored
    {"n": 9, "score": 10, "southeast": True},    # out of range: ignored
    {"n": 2, "score": 99, "southeast": "yes"},   # malformed flag: ignored
    {"n": 3, "score": 99, "southeast": False},   # score clamped to 10
]), batch)
assert (batch[0]["ai_score"], batch[0]["southeast"]) == (8, True)
assert "southeast" not in batch[1]
assert batch[2]["ai_score"] == 10

print("pipeline: all checks pass")
