# filter.py
# Keyword-based article categorizer.
# Articles are matched against each category's keywords (case-insensitive, title only).
# An article can appear in multiple categories if it matches more than one.
# Articles that match nothing go into "General" as a catch-all for later AI review.

CATEGORIES = {
    "AI & Data Centers": [
        "artificial intelligence", " ai ", "machine learning", "deep learning",
        "data center", "datacenter", "data centre", "hyperscaler",
        "gpu", "nvidia", "microsoft azure", "google cloud", "amazon aws",
        "cloud computing", "llm", "large language model", "generative ai",
        "chatgpt", "openai", "anthropic", "meta ai",
        "power demand", "compute", "inference", "training cluster",
    ],
    "Renewables": [
        "solar", "wind", "hydro", "hydropower", "hydroelectric",
        "geothermal", "renewable", "clean energy", "green energy",
        "offshore wind", "onshore wind", "wind farm", "wind turbine",
        "solar panel", "solar farm", "photovoltaic", "pv ",
        "battery storage", "energy storage", "grid storage",
        "pumped hydro", "tidal", "wave energy",
    ],
    "Nuclear": [
        "nuclear", "reactor", "uranium", "enrichment", "fission",
        "fusion", "small modular reactor", "smr", "pressurized water",
        "boiling water reactor", "spent fuel", "nuclear waste",
        "vogtle", "westinghouse", "electricite de france", "edf",
        "iaea", "nonproliferation", "nuclear power plant",
    ],
    "Hydrocarbons": [
        "natural gas", "lng", "liquefied natural gas", "pipeline",
        "coal", "oil", "crude", "petroleum", "refinery", "refining",
        "gasoline", "diesel", "fossil fuel", "carbon", "methane",
        "shale", "fracking", "hydraulic fracturing", "offshore drilling",
        "opec", "oilfield", "gas field", "barrel", "btu",
        "petrochemical", "propane", "ethane", "ngl",
    ],
    "Georgia & Southeast US": [
        "georgia", "atlanta", "savannah", "augusta",
        "alabama", "florida", "tennessee", "south carolina", "north carolina",
        "mississippi", "louisiana", "arkansas", "kentucky",
        "southeastern", "southeast us", "appalachian",
        "southern company", "georgia power", "duke energy", "dominion energy",
        "tennessee valley authority", "tva", "entergy",
        "gulf coast", "port of savannah",
    ],
}

# Category display order in the email
CATEGORY_ORDER = [
    "AI & Data Centers",
    "Renewables",
    "Nuclear",
    "Hydrocarbons",
    "Georgia & Southeast US",
    "General",
]


def categorize(article: dict) -> list[str]:
    """
    Return a list of category names this article belongs to.
    Falls back to ["General"] if no keywords match.
    """
    title = article.get("title", "").lower()
    # Pad with spaces so word-boundary checks work at start/end of title
    padded = f" {title} "

    matched = []
    for category, keywords in CATEGORIES.items():
        for kw in keywords:
            if kw in padded:
                matched.append(category)
                break  # one match per category is enough

    return matched if matched else ["General"]


from difflib import SequenceMatcher


def similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()


def deduplicate(articles: list[dict], threshold: float = 0.85) -> list[dict]:
    """
    Remove near-duplicate articles based on title similarity.
    Keeps the first occurrence, drops subsequent similar titles.
    """
    seen = []
    unique = []
    for article in articles:
        title = article["title"]
        is_duplicate = any(similarity(title, seen_title) >= threshold for seen_title in seen)
        if not is_duplicate:
            seen.append(title)
            unique.append(article)
    return unique


def filter_and_categorize(articles: list[dict]) -> dict[str, list[dict]]:
    """
    Take a flat list of articles and return a dict of {category: [articles]}.
    An article can appear under multiple categories.
    """
    result: dict[str, list[dict]] = {cat: [] for cat in CATEGORY_ORDER}

    for article in articles:
        categories = categorize(article)
        for cat in categories:
            if cat not in result:
                result[cat] = []
            result[cat].append(article)

    # Remove empty categories
    return {k: v for k, v in result.items() if v}
