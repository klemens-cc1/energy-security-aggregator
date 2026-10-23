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

print("pipeline: all checks pass")
