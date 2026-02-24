from difflib import SequenceMatcher
import logging
import os
import time

log = logging.getLogger(__name__)

CATEGORY_DESCRIPTIONS = {
    "AI & Data Centers": "artificial intelligence, machine learning, data centers, GPU infrastructure, cloud computing, and their energy/power demands",
    "Renewables": "solar, wind, hydro, geothermal, tidal, battery storage, and other renewable energy sources and projects",
    "Nuclear": "nuclear power plants, reactors, uranium, SMRs, fusion energy, nuclear fuel, and the nuclear energy industry",
    "Hydrocarbons": "oil, natural gas, LNG, coal, petroleum, pipelines, refineries, fossil fuels, and hydrocarbon markets",
    "Georgia & Southeast US": "energy news specific to Georgia, Alabama, Florida, Tennessee, South Carolina, North Carolina, or the broader southeastern US energy sector including utilities like Georgia Power, Southern Company, Duke Energy, TVA, and Entergy",
}

CATEGORIES = {
    "AI & Data Centers": [
        "artificial intelligence", "machine learning", "deep learning",
        "data center", "datacenter", "data centre", "hyperscaler",
        "gpu", "nvidia", "microsoft azure", "google cloud", "amazon aws",
        "cloud computing", "llm", "large language model", "generative ai",
        "chatgpt", "openai", "anthropic", "meta ai",
        "ai energy", "ai power", "ai electricity", "ai infrastructure",
        "compute", "training cluster",
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
        "nuclear power", "nuclear energy", "nuclear plant", "nuclear reactor",
        "nuclear fuel", "nuclear waste", "nuclear grid", "nuclear capacity",
        "nuclear generation", "nuclear station", "nuclear industry",
        "reactor", "uranium", "enrichment", "fission",
        "fusion energy", "fusion reactor", "fusion power",
        "small modular reactor", "smr", "pressurized water reactor",
        "boiling water reactor", "spent fuel",
        "vogtle", "westinghouse", "electricite de france", "edf",
        "nonproliferation",
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
        "georgia power", "georgia energy", "georgia solar",
        "georgia nuclear", "georgia grid", "georgia utility",
        "georgia public service commission", "georgia psc",
        "plant vogtle", "southern company",
        "tennessee valley authority", "tva",
        "duke energy", "dominion energy", "entergy",
        "southeastern energy", "southeast energy",
        "southeast power", "southeast grid",
        "appalachian power", "alabama power", "mississippi power",
        "gulf coast energy", "gulf power",
    ],
}

CATEGORY_ORDER = [
    "AI & Data Centers",
    "Renewables",
    "Nuclear",
    "Hydrocarbons",
    "Georgia & Southeast US",
]

AI_RELEVANCE_THRESHOLD = 6
AI_SCORE_LIMIT = 150

# Lower index = more specific. Articles in multiple categories
# are kept only in the most specific one.
CATEGORY_SPECIFICITY = [
    "Georgia & Southeast US",
    "Nuclear",
    "Hydrocarbons",
    "AI & Data Centers",
    "Renewables",
]


def resolve_cross_category_duplicates(categorized: dict) -> dict:
    """Keep each article only in its most specific category."""
    url_to_best_cat: dict[str, str] = {}
    for cat in CATEGORY_SPECIFICITY:
        for article in categorized.get(cat, []):
            url = article["url"]
            if url not in url_to_best_cat:
                url_to_best_cat[url] = cat

    resolved: dict = {cat: [] for cat in CATEGORY_ORDER}
    cross_dupes = 0
    for cat, articles in categorized.items():
        for article in articles:
            best = url_to_best_cat.get(article["url"], cat)
            if best == cat:
                resolved[cat].append(article)
            else:
                cross_dupes += 1
                log.info(
                    f"  CROSS-CAT DUPE: '{article['title'][:60]}' "
                    f"kept in {best}, removed from {cat}"
                )

    if cross_dupes:
        log.info(f"Cross-category deduplication: {cross_dupes} duplicate(s) removed.")

    return {k: v for k, v in resolved.items() if v}


def similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()


def deduplicate(articles: list[dict], threshold: float = 0.85) -> list[dict]:
    seen = []
    unique = []
    for article in articles:
        title = article["title"]
        is_duplicate = any(similarity(title, t) >= threshold for t in seen)
        if not is_duplicate:
            seen.append(title)
            unique.append(article)
    return unique


def categorize(article: dict) -> list[str]:
    title = article.get("title", "").lower()
    padded = f" {title} "
    matched = []
    for category, keywords in CATEGORIES.items():
        for kw in keywords:
            if kw in padded:
                matched.append(category)
                break
    return matched


def score_article(title: str, category: str, client) -> int:
    description = CATEGORY_DESCRIPTIONS.get(category, category)
    prompt = (
        f'Rate how relevant this news article title is to the topic of "{description}" '
        f'for an energy security newsletter focused on power generation, electricity grids, '
        f'and energy infrastructure. '
        f'Score LOW (1-3) for: military hardware, weapons, vehicles, aircraft, geopolitics without energy angle, '
        f'general technology without energy relevance. '
        f'Score HIGH (7-10) for: power plants, electricity demand, grid infrastructure, energy policy, '
        f'fuel production, energy storage, data center power consumption. '
        f'Reply with ONLY a single integer from 1 to 10.\n\n'
        f'Title: {title}'
    )
    try:
        time.sleep(2.5)
        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=5,
            temperature=0,
        )
        text = response.choices[0].message.content.strip()
        score = int(''.join(filter(str.isdigit, text))[:2])
        return min(max(score, 1), 10)
    except Exception as e:
        log.warning(f"AI scoring failed for '{title}': {e}")
        return 5


def ai_filter(categorized: dict) -> dict:
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        log.warning("GROQ_API_KEY not set — skipping AI filter.")
        return categorized

    try:
        from groq import Groq
        client = Groq(api_key=api_key)
    except ImportError:
        log.warning("groq package not installed — skipping AI filter.")
        return categorized

    to_score = []
    for category, articles in categorized.items():
        for article in articles:
            to_score.append((category, article))

    if len(to_score) > AI_SCORE_LIMIT:
        log.warning(f"Capping AI scoring at {AI_SCORE_LIMIT} articles (had {len(to_score)})")
        to_score = to_score[:AI_SCORE_LIMIT]

    log.info(f"AI scoring {len(to_score)} articles via Groq...")

    def score_item(item):
        category, article = item
        score = score_article(article["title"], category, client)
        return category, article, score

    results = []
    for item in to_score:
        try:
            results.append(score_item(item))
        except Exception as e:
            log.warning(f"Scoring failed: {e}")

    filtered: dict = {cat: [] for cat in CATEGORY_ORDER}
    passed = 0
    dropped = 0
    for category, article, score in results:
        if score >= AI_RELEVANCE_THRESHOLD:
            filtered[category].append(article)
            passed += 1
        else:
            dropped += 1
            log.info(f"  DROPPED (score {score}): {article['title'][:80]}")

    log.info(f"AI filter: {passed} passed, {dropped} dropped.")
    return {k: v[:10] for k, v in filtered.items() if v}


def filter_and_categorize(articles: list[dict]) -> dict:
    result: dict = {cat: [] for cat in CATEGORY_ORDER}
    for article in articles:
        for cat in categorize(article):
            result.setdefault(cat, []).append(article)

    result = {k: v for k, v in result.items() if v}
    total = sum(len(v) for v in result.values())
    log.info(f"Keyword filter: {total} article slots across {len(result)} categories.")

    result = ai_filter(result)
    result = resolve_cross_category_duplicates(result)
    return result
