"""Broker registry: load the catalogue, score likely exposure, build lookup URLs.

The honest version of "which brokers have my data":

  1. Deterministic inference. A broker's business model tells you who it holds.
     If you have a US credit file, LexisNexis Risk has you. Not a guess.
  2. One-click manual verification. We build the deep link into each broker's
     own people-search page; you look, and mark found / not found.

What we deliberately do NOT do is scrape people-search results. Those sites sit
behind Cloudflare, their terms forbid it, and defeating the bot check is the
part of this problem that gets you blocked rather than deleted.
"""
import json
import re
import urllib.parse
from pathlib import Path

DATA_FILE = Path(__file__).resolve().parent.parent / "data" / "brokers.json"

# Profile traits the UI collects, and what each one implies.
TRAITS = [
    ("us_resident",     "I live (or have lived) in the United States"),
    ("eu_resident",     "I live in the EU / UK"),
    ("has_us_credit",   "I have a US credit file (card, loan, mortgage)"),
    ("has_bank_account", "I have a US bank account"),
    ("employed",        "I've been employed by a US company"),
    ("owns_property",   "I own or have owned property"),
    ("rents_home",      "I've rented a home or apartment"),
    ("has_insurance",   "I have US auto/home/health insurance"),
    ("social_media",    "I use social media under my real name"),
    ("online_shopping", "I shop online / have used my email at checkout"),
    ("loyalty_programs", "I use store loyalty or rewards cards"),
    ("mobile_apps",     "I use mobile apps with location permissions"),
]

CATEGORY_LABELS = {
    "people_search": "People search",
    "marketing": "Marketing data",
    "adtech": "Ad tech / identity graph",
    "risk": "Risk & screening",
    "credit": "Credit bureau",
}

ACTION_LABELS = {
    "deletion": "Delete my data",
    "suppression": "Remove my listing",
    "sale_optout": "Do not sell/share",
    "freeze": "Freeze & disclose",
    "prescreen_optout": "Stop prescreened offers",
}


def load() -> list[dict]:
    with open(DATA_FILE, encoding="utf-8") as fh:
        return json.load(fh)["brokers"]


def by_id(broker_id: str) -> dict | None:
    return next((b for b in load() if b["id"] == broker_id), None)


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def search_url(broker: dict, profile: dict) -> str | None:
    """Deep link into the broker's own search, so you can eyeball your listing.

    Falls back to a site-scoped web search when we don't know the URL shape.
    """
    name = (profile.get("full_name") or "").strip()
    if not name:
        return None

    parts = name.split()
    first, last = parts[0], (parts[-1] if len(parts) > 1 else "")
    city_state = (profile.get("state") or "").strip()

    tpl = broker.get("search_url")
    if tpl:
        return (
            tpl.replace("{name_slug}", _slug(name))
            .replace("{name_query}", urllib.parse.quote_plus(name))
            .replace("{location_query}", urllib.parse.quote_plus(city_state))
            .replace("{first}", urllib.parse.quote(first))
            .replace("{last}", urllib.parse.quote(last))
        )

    # No known template - scope a search engine to the broker's domain instead.
    q = f'site:{broker["domain"]} "{name}"'
    if city_state:
        q += f" {city_state}"
    return "https://duckduckgo.com/?q=" + urllib.parse.quote_plus(q)


def likelihood(broker: dict, profile: dict) -> tuple[str, str]:
    """Return (level, reason) for whether this broker probably holds you.

    level is one of: certain, likely, possible, unlikely
    """
    traits = set(profile.get("traits") or [])
    country = (profile.get("country") or "US").upper()
    juris = broker.get("jurisdictions", [])

    if country == "US" and "US" not in juris:
        return "unlikely", "Operates outside your jurisdiction"
    if country != "US" and "US" in juris and "EU" not in juris:
        return "possible", "US-focused broker; may still hold records on you"

    trigs = broker.get("triggers", [])
    hits = [t for t in trigs if t in traits]

    if not trigs:
        return "possible", "No specific trigger recorded for this broker"
    if not hits:
        return "unlikely", "None of your profile facts match this broker's inputs"

    labels = dict(TRAITS)
    reason = "; ".join(labels.get(h, h) for h in hits)

    # Brokers that buy public records wholesale don't cherry-pick. If you exist
    # in the US as an adult, they have you - there is no "maybe" about it.
    if broker["category"] in ("people_search", "risk", "credit") and "us_resident" in traits:
        return "certain", reason
    if len(hits) >= 2:
        return "likely", reason
    return "likely" if broker["category"] == "marketing" else "possible", reason


LIKELIHOOD_RANK = {"certain": 0, "likely": 1, "possible": 2, "unlikely": 3}


def scan(profile: dict, statuses: dict) -> list[dict]:
    """Annotate every broker with exposure level, lookup URL and current status."""
    out = []
    for b in load():
        level, reason = likelihood(b, profile)
        st = statuses.get(b["id"], {})
        out.append(
            {
                **b,
                "category_label": CATEGORY_LABELS.get(b["category"], b["category"]),
                "action_label": ACTION_LABELS.get(b["action"], b["action"]),
                "likelihood": level,
                "reason": reason,
                "search_url": search_url(b, profile),
                "status": st.get("state", "unknown"),
                "status_notes": st.get("notes", ""),
            }
        )
    out.sort(key=lambda b: (LIKELIHOOD_RANK[b["likelihood"]], b["name"].lower()))
    return out
