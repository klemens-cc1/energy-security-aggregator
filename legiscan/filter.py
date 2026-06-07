import logging

log = logging.getLogger(__name__)

# ── Local SQL keyword list ─────────────────────────────────────────────────────
# Used for local SQLite filtering — compound terms only, same false-positive rules
# as the RSS aggregator: bare nouns ("energy", "power", "utility") excluded.
SEARCH_KEYWORDS = [
    "electric utility", "public utility commission", "public service commission",
    "integrated resource plan", "transmission line", "interconnection queue",
    "grid reliability", "grid resilience", "energy storage", "battery storage",
    "long duration storage", "nuclear reactor", "nuclear power plant",
    "small modular reactor", "nuclear energy", "offshore wind",
    "renewable energy standard", "clean energy standard",
    "renewable portfolio standard", "hydroelectric dam",
    "natural gas pipeline", "liquefied natural gas", "coal power plant",
    "electricity deregulation", "retail electricity", "net metering",
    "community solar", "rate case", "electricity rate", "electric grid",
    "bulk power system", "power generation", "solar energy", "wind energy",
    "nuclear fuel", "coal plant", "demand response", "electricity market",
    "utility regulation", "power purchase agreement", "capacity market",
    "data center load", "data center power", "behind the meter",
    "electric vehicle charging", "hydrogen energy", "fusion energy",
    "grid enhancing technology",
]


# ── Tiered query taxonomy ──────────────────────────────────────────────────────
# Tier 1: high precision compound terms — run every delta, auto-fetch getBill
# Tier 2: medium precision — run every delta, fusion score required before getBill
# Tier 3: emerging/niche topics — run every delta, higher fusion threshold

QUERIES = {
    1: [
        # Grid infrastructure
        "electric utility",
        "public utility commission",
        "public service commission",
        "integrated resource plan",
        "transmission line siting",
        "interconnection queue",
        "grid reliability",
        "grid resilience",
        "energy storage",
        "battery storage",
        "long duration storage",
        # Generation — compound only
        "nuclear reactor",
        "nuclear power plant",
        "small modular reactor",
        "nuclear energy",
        "offshore wind",
        "renewable energy standard",
        "clean energy standard",
        "renewable portfolio standard",
        "hydroelectric dam",
        # Fuels — compound only
        "natural gas pipeline",
        "liquefied natural gas",
        "coal power plant",
        # Market structure
        "electricity deregulation",
        "retail electricity",
        "net metering",
        "community solar",
        "rate case",
        "electricity rate",
    ],
    2: [
        # Medium precision — need fusion score support before fetching
        "electric grid",
        "bulk power system",
        "distribution system",
        "power generation",
        "energy transmission",
        "solar energy",
        "wind energy",
        "nuclear fuel",
        "coal plant",
        "demand response",
        "electricity market",
        "utility regulation",
        "power purchase agreement",
        "capacity market",
        "energy efficiency",
    ],
    3: [
        # Emerging / datacenter-load angle
        "data center load",
        "data center power",
        "behind the meter",
        "electric vehicle charging",
        "vehicle to grid",
        "hydrogen energy",
        "fusion energy",
        "microreactor",
        "virtual power plant",
        "grid enhancing technology",
        "advanced conductor",
    ],
}

# Tier weights for fusion score
TIER_WEIGHT = {1: 3.0, 2: 2.0, 3: 1.5}

# Fusion score thresholds — calibrated against GA distribution (median=2.8, max=279)
FETCH_NOW_THRESHOLD   = 20.0  # top ~8% of candidates — fetch getBill immediately
FETCH_BATCH_THRESHOLD = 10.0  # top ~14% — fetch in nightly batch
PER_STATE_CAP         = 100   # hard ceiling per state per delta run
# below FETCH_BATCH_THRESHOLD → hold/discard


def compute_fusion_score(hits: list[dict]) -> float:
    """
    hits: list of {"tier": int, "relevance": float (0-100)} from search results.
    fusion = sum of (relevance/100 * tier_weight) across distinct queries,
             boosted by number of distinct query matches.
    """
    if not hits:
        return 0.0
    score = sum((h["relevance"] / 100.0) * TIER_WEIGHT[h["tier"]] for h in hits)
    distinct_queries = len(set(h["query"] for h in hits))
    return round(score * (1 + 0.2 * (distinct_queries - 1)), 3)


def triage(fusion_score: float) -> str:
    """Returns 'now', 'batch', or 'hold'."""
    if fusion_score >= FETCH_NOW_THRESHOLD:
        return "now"
    elif fusion_score >= FETCH_BATCH_THRESHOLD:
        return "batch"
    return "hold"


# Negative signals — if these appear alone without energy context, deprioritize
NEGATIVE_SIGNALS = [
    "nuclear family",
    "power of attorney",
    "police power",
    "workforce pipeline",
    "talent pipeline",
    "drug pipeline",
    "solar panels on",      # retail/consumer, not grid policy
    "utility vehicle",
    "utility room",
    "storage unit",
    "storage facility",     # non-energy storage contexts
]


def has_negative_signal(text: str) -> bool:
    t = text.lower()
    return any(neg in t for neg in NEGATIVE_SIGNALS)


def keyword_tags(text: str) -> list[str]:
    """Fallback tag inference when LLM is unavailable."""
    t = f" {text.lower()} "
    tag_map = {
        "nuclear":          ["nuclear reactor", "nuclear power", "nuclear plant", "small modular reactor", "uranium", "fusion"],
        "solar/wind":       ["solar energy", "wind energy", "offshore wind", "wind farm", "photovoltaic"],
        "transmission":     ["transmission line", "interconnection", "electric grid", "substation", "grid reliability"],
        "storage":          ["battery storage", "energy storage", "long duration storage", "pumped hydro"],
        "data center load": ["data center", "behind the meter", "electric vehicle charging"],
        "market reform":    ["deregulation", "rate case", "net metering", "capacity market", "community solar"],
        "grid resilience":  ["grid resilience", "grid reliability", "bulk power", "demand response"],
    }
    return [tag for tag, kws in tag_map.items() if any(kw in t for kw in kws)]
