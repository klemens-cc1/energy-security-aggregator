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
        "natural gas", "lng", "liquefied natural gas",
        "oil pipeline", "gas pipeline", "crude oil", "petroleum",
        "oil refinery", "refining", "gasoline", "diesel fuel",
        "fossil fuel", "coal mine", "coal plant", "coal power",
        "shale gas", "fracking", "hydraulic fracturing",
        "offshore drilling", "opec", "oilfield", "oil field",
        "oil price", "gas price", "oil production", "gas production",
        "barrel of oil", "brent crude", "wti crude",
        "petrochemical", "oil major", "oil company",
        "exxon", "chevron", "bp ", "shell oil", "totalenergies",
        "liquefied petroleum", "propane", "natural gas pipeline",
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

    # Cap each category at 10 articles and remove empty categories
    return {k: v[:10] for k, v in result.items() if v}
