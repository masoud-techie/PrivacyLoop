"""Send queued drafts in controlled batches.

Clicking through 22 confirmation boxes is tedious, but blasting 22 near-identical
emails out of a personal Gmail in sixty seconds is how you get your mail filed as
spam - by Google on the way out, and by the brokers' own filters on the way in.

So: small batches, spaced out, and you must pass --yes to send anything.

    python tools/send_batch.py                      # dry preview, sends nothing
    python tools/send_batch.py --limit 5 --yes      # send 5, ~45s apart
    python tools/send_batch.py --limit 5 --yes --delay 120

Run it once a day until the queue drains. Form-channel requests are skipped -
those you submit by hand in the web UI.
"""
import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import db, mailer  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=5, help="max to send (default 5)")
    ap.add_argument("--delay", type=int, default=45, help="seconds between sends")
    ap.add_argument("--yes", action="store_true", help="actually send")
    args = ap.parse_args()

    cfg = mailer.load_config()
    drafts = [r for r in db.list_requests("draft")
              if r["channel"] == "email" and r["to_email"]]

    if not drafts:
        print("No email drafts queued. Anything left is form-only - do those in the UI.")
        return 0

    batch = drafts[:args.limit]
    print(f"{len(drafts)} email drafts queued, taking {len(batch)}:\n")
    for r in batch:
        print(f"  #{r['id']:<4} {r['broker_name']:<40} -> {r['to_email']}")

    if cfg["dry_run"]:
        print("\ndry_run is TRUE in config.json - nothing will actually be emailed.")
    if not args.yes:
        print("\nPreview only. Re-run with --yes to send.")
        return 0
    if cfg["dry_run"]:
        print("Set \"dry_run\": false before --yes will do anything real.")
        return 1

    print(f"\nSending {len(batch)}, {args.delay}s apart. Ctrl+C to stop.\n")
    sent = failed = 0
    for i, r in enumerate(batch):
        ok, detail = mailer.send(r["id"], r["to_email"], r["subject"], r["body"])
        if ok:
            db.mark_sent(r["id"], r["law"], detail)
            sent += 1
            print(f"  [{i+1}/{len(batch)}] SENT  {r['broker_name']}")
        else:
            db.log_event(r["id"], "send_failed", detail)
            failed += 1
            print(f"  [{i+1}/{len(batch)}] FAIL  {r['broker_name']}: {detail}")
        if i < len(batch) - 1:
            try:
                time.sleep(args.delay)
            except KeyboardInterrupt:
                print("\nStopped. Already-sent requests are recorded.")
                break

    print(f"\n{sent} sent, {failed} failed, {len(drafts) - sent} still queued.")
    if sent:
        print("Deadlines are now tracked - check the dashboard for overdue ones.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
