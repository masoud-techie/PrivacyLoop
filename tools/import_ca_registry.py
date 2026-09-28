"""Bulk-import California's data broker registry.

This is the single best trick in the whole project. California's Delete Act
(AB 1202 / SB 362) makes every data broker doing business in the state REGISTER
with the California Privacy Protection Agency and publish its opt-out URL and
contact email. The result is a public CSV of ~500 brokers - a far better list
than anything you could assemble by hand, and it is the same list the commercial
services work from.

How to use it:

  1. Go to https://cppa.ca.gov/data_broker_registry/ and download the registry
     export (it is also mirrored on https://data.ca.gov as a CSV resource).
  2. python tools/import_ca_registry.py ~/Downloads/data-broker-registry.csv

Column names have changed between editions, so this matches them loosely rather
than assuming a fixed header. Imported entries land with "verified": false and
conservative defaults - review before mass-mailing 500 companies.
"""
import argparse
import csv
import json
import re
import sys
from pathlib import Path
from urllib.parse import urlparse

DATA = Path(__file__).resolve().parent.parent / "data" / "brokers.json"

# Loose header matching: (our field, list of substrings to look for)
COLUMN_HINTS = [
    ("name",        ["business name", "broker name", "company", "name"]),
    ("optout_url",  ["deletion", "opt-out", "opt out", "website", "url", "link"]),
    ("privacy_email", ["email"]),
    ("notes",       ["additional information", "notes", "description"]),
]


def pick_columns(header: list[str]) -> dict[str, str]:
    lowered = {h: h.lower().strip() for h in header}
    chosen: dict[str, str] = {}
    for field, hints in COLUMN_HINTS:
        for hint in hints:
            match = next((h for h, low in lowered.items()
                          if hint in low and h not in chosen.values()), None)
            if match:
                chosen[field] = match
                break
    return chosen


def slugify(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")
    return s[:48] or "broker"


def domain_of(url: str, fallback: str) -> str:
    try:
        host = urlparse(url if "://" in url else "https://" + url).netloc
        return host.removeprefix("www.") or fallback
    except ValueError:
        return fallback


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("csv_path", type=Path)
    ap.add_argument("--limit", type=int, default=0, help="import at most N rows")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    if not args.csv_path.exists():
        print(f"No such file: {args.csv_path}")
        return 1

    doc = json.loads(DATA.read_text(encoding="utf-8"))
    existing_ids = {b["id"] for b in doc["brokers"]}
    existing_domains = {b["domain"].lower() for b in doc["brokers"]}

    with open(args.csv_path, newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        if not reader.fieldnames:
            print("Empty or unreadable CSV.")
            return 1
        cols = pick_columns(list(reader.fieldnames))
        if "name" not in cols:
            print(f"Couldn't find a name column in: {reader.fieldnames}")
            return 1
        print(f"Column mapping: {cols}\n")

        added = skipped = 0
        for row in reader:
            name = (row.get(cols["name"]) or "").strip()
            if not name:
                continue
            url = (row.get(cols.get("optout_url", "")) or "").strip()
            email = (row.get(cols.get("privacy_email", "")) or "").strip()
            notes = (row.get(cols.get("notes", "")) or "").strip()[:300]

            bid = slugify(name)
            dom = domain_of(url, f"{bid}.example")
            if bid in existing_ids or dom.lower() in existing_domains:
                skipped += 1
                continue

            doc["brokers"].append({
                "id": bid,
                "name": name,
                "domain": dom,
                "category": "marketing",
                "action": "deletion",
                "method": "form" if url else "email",
                "optout_url": url or None,
                "privacy_email": email or None,
                "search_url": None,
                "jurisdictions": ["US"],
                "triggers": ["us_resident"],
                "fcra": False,
                "verified": False,
                "source": "CA CPPA data broker registry",
                "notes": notes,
            })
            existing_ids.add(bid)
            existing_domains.add(dom.lower())
            added += 1
            if args.limit and added >= args.limit:
                break

    print(f"{added} new brokers, {skipped} already known.")
    if args.dry_run:
        print("Dry run - registry not written.")
        return 0

    DATA.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Wrote {DATA}. Registry now holds {len(doc['brokers'])} brokers.")
    print("Imported rows default to category 'marketing' / action 'deletion'."
          " Re-categorise the ones you care about.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
