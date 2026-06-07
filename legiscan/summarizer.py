import json
import logging
import os

log = logging.getLogger(__name__)

PROMPT = """\
You are an energy security policy analyst. Read the following state legislative bill and respond with a JSON object containing three fields:

- "summary": 1-2 sentences describing what the bill does and its significance to energy infrastructure or supply security
- "tags": an array of applicable tags from this list only: ["nuclear", "solar/wind", "transmission", "storage", "data center load", "market reform", "grid resilience"]
- "confidence": a float from 0.0 to 1.0 indicating how relevant this bill is to energy security (1.0 = clearly central to energy infrastructure; 0.0 = tangentially related at best)

Respond with valid JSON only. No explanation, no markdown, no code fences.

Bill state: {state}
Bill number: {bill_number}
Bill title: {title}
Bill text:
{text}
"""


def summarize(state: str, bill_number: str, title: str, text: str) -> dict | None:
    """
    Returns {"summary": str, "tags": list[str], "confidence": float} or None on failure.
    """
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        log.warning("GROQ_API_KEY not set — skipping summarization")
        return None

    try:
        from groq import Groq
    except ImportError:
        log.warning("groq package not installed — skipping summarization")
        return None

    client = Groq(api_key=api_key)
    prompt = PROMPT.format(
        state=state,
        bill_number=bill_number,
        title=title,
        text=text[:8000],
    )

    # Reject text that is clearly binary garbage
    non_ascii = sum(1 for c in text if ord(c) > 127)
    if len(text) > 100 and non_ascii / len(text) > 0.15:
        log.debug(f"Skipping {state} {bill_number}: text looks like binary ({non_ascii}/{len(text)} non-ASCII)")
        return None

    try:
        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=400,
            temperature=0,
            response_format={"type": "json_object"},
        )
        raw = response.choices[0].message.content.strip()

        if not raw:
            log.debug(f"Empty Groq response for {state} {bill_number}")
            return None

        result = json.loads(raw)

        if not all(k in result for k in ("summary", "tags", "confidence")):
            raise ValueError(f"Missing keys in response: {result}")

        result["confidence"] = float(result["confidence"])
        result["tags"] = [t for t in result["tags"] if isinstance(t, str)]
        return result

    except Exception as e:
        log.warning(f"Summarization failed for {state} {bill_number}: {e}")
        return None
