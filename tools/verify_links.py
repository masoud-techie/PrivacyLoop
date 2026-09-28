"""Check that every opt-out URL in the registry still resolves.

Broker opt-out pages rot fast - companies merge, rebrand, and quietly move the
form somewhere harder to find. Run this monthly. Anything that 404s or times out
needs a human to go find the new page.

    python tools/verify_links.py
    python tools/verify_links.py --fix   # mark reachable entries as verified

Note a 403 is not necessarily a dead link: Cloudflare blocks this script's user
agent on several people-search sites. Those need a manual eyeball in a browser.
"""
import argparse
import json
import sys
from pathlib import Path

import requests

DATA = Path(__file__).resolve().parent.parent / "data" / "brokers.json"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) PrivacyLoop/1.0 link-checker"

VERDICTS = {
    "ok": "\033[92mOK   \033[0m",
    "moved": "\033[93mMOVED\033[0m",
    "blocked": "\033[93mBLOCK\033[0m",
    "dead": "\033[91mDEAD \033[0m",
}


def check(url: str) -> tuple[str, str]:
    try:
        r = requests.get(url, timeout=15, allow_redirects=True,
                         headers={"User-Agent": UA})
    except requests.RequestException as exc:
        return "dead", type(exc).__name__

    if r.status_code in (403, 429):
        return "blocked", f"HTTP {r.status_code} - bot protection, check by hand"
    if r.status_code >= 400:
        return "dead", f"HTTP {r.status_code}"
    if r.url.rstrip("/") != url.rstrip("/"):
        return "moved", f"-> {r.url}"
    return "ok", f"HTTP {r.status_code}"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--fix", action="store_true",
                    help='set "verified": true on entries that respond OK')
    args = ap.parse_args()

    doc = json.loads(DATA.read_text(encoding="utf-8"))
    problems = 0

    for b in doc["brokers"]:
        url = b.get("optout_url")
        if not url:
            print(f"{VERDICTS['dead']} {b['name']:<45} no opt-out URL recorded")
            problems += 1
            continue
        verdict, detail = check(url)
        print(f"{VERDICTS[verdict]} {b['name']:<45} {detail}")
        if verdict == "ok" and args.fix:
            b["verified"] = True
        elif verdict != "ok":
            problems += 1

    if args.fix:
        DATA.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n",
                        encoding="utf-8")
        print("\nRegistry updated.")

    print(f"\n{len(doc['brokers']) - problems}/{len(doc['brokers'])} clean, "
          f"{problems} need attention.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
