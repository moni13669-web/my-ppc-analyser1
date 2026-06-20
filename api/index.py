import re
import time
import random
import requests
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

AMAZON_DOMAIN = "www.amazon.in"

# Simple in-memory cache so repeat requests for the same ASIN (e.g. on a
# warm serverless instance, or a page refresh) don't re-hit Amazon at all.
# This resets on cold start — it's a bonus, not your only cache. The real
# persistent cache lives in the frontend (catalogData), unchanged.
_TITLE_CACHE: dict[str, str] = {}

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.4 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
]

BOT_CHECK_PATTERN = re.compile(
    r"^(sorry|robot check|amazon\.in$|amazon\.in:?\s*$|continue shopping|enter the characters)",
    re.IGNORECASE,
)


def clean_amazon_title(raw_title: str | None) -> str | None:
    """Mirrors the frontend's cleanAmazonTitle() logic, ported to Python."""
    if not raw_title:
        return None

    t = raw_title
    t = t.replace("&amp;", "&")
    t = re.sub(r"&#39;|&#x27;|&apos;", "'", t, flags=re.IGNORECASE)
    t = t.replace("&quot;", '"')
    t = re.sub(r"&nbsp;", " ", t, flags=re.IGNORECASE)
    t = re.sub(r"&ndash;", "–", t, flags=re.IGNORECASE)
    t = re.sub(r"&mdash;", "—", t, flags=re.IGNORECASE)
    t = t.strip()

    if BOT_CHECK_PATTERN.match(t):
        return None

    t = re.split(r"\s*:\s*Amazon\.\w+(?:\.\w+)?\b.*$", t, flags=re.IGNORECASE)[0]
    t = re.split(r"\s+\|\s+Amazon\.\w+.*$", t, flags=re.IGNORECASE)[0]
    t = re.sub(r"\s+(at|on)\s+Amazon\.\w+(?:\.\w+)?\s*$", "", t, flags=re.IGNORECASE)
    t = re.sub(r"^Amazon\.\w+(?:\.\w+)?:\s*", "", t, flags=re.IGNORECASE)
    t = re.sub(r"^Buy\s+", "", t, flags=re.IGNORECASE)
    t = re.sub(r"\s+online\s+at\s+(low|best|lowest)\s+price.*$", "", t, flags=re.IGNORECASE)
    t = re.sub(r"\s+-\s+Amazon\.\w+(\.\w+)?$", "", t, flags=re.IGNORECASE)
    t = t.strip()

    if not t or re.match(r"^amazon", t, re.IGNORECASE) or len(t) < 4:
        return None
    return t


@app.get("/api/fetch-title/{asin}")
def fetch_title(asin: str):
    asin = asin.strip().upper()

    if asin in _TITLE_CACHE:
        return {"success": True, "title": _TITLE_CACHE[asin]}

    product_url = f"https://{AMAZON_DOMAIN}/dp/{asin}"
    headers = {
        "User-Agent": random.choice(USER_AGENTS),
        "Accept-Language": "en-IN,en;q=0.9",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }

    # Small random delay so requests don't fire in an obviously robotic
    # fixed-interval pattern. Kept short to stay well inside Vercel's
    # Hobby-tier 10s function timeout.
    time.sleep(random.uniform(0.2, 0.6))

    try:
        resp = requests.get(product_url, headers=headers, timeout=7)
    except requests.RequestException:
        return {"success": False, "title": "No matching title found"}

    if resp.status_code != 200:
        return {"success": False, "title": "No matching title found"}

    match = re.search(r"<title[^>]*>([\s\S]*?)</title>", resp.text, re.IGNORECASE)
    if not match:
        return {"success": False, "title": "No matching title found"}

    title = clean_amazon_title(match.group(1))
    if not title:
        return {"success": False, "title": "No matching title found"}

    _TITLE_CACHE[asin] = title
    return {"success": True, "title": title}
