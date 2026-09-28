"""Prove your SMTP settings work before you aim them at a data broker.

Sends one harmless test message from you, to you. Ignores dry_run on purpose -
that is the whole point of the script.

    python tools/test_smtp.py                 # send to your from_email
    python tools/test_smtp.py you@other.com   # send somewhere else

If this fails, fix it here rather than debugging against a real request.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import mailer  # noqa: E402

HINTS = {
    "SMTPAuthenticationError": (
        "Gmail rejected the login. Almost always one of:\n"
        "  - You used your account password. Gmail needs an APP PASSWORD:\n"
        "    https://myaccount.google.com/apppasswords (2FA must be on first)\n"
        "  - The app password still has its spaces in it. Strip them.\n"
        "  - smtp_user is not the full address (needs you@gmail.com, not 'you')."
    ),
    "SMTPServerDisconnected": "Server hung up. Check smtp_host and smtp_port (587 for STARTTLS).",
    "SMTPConnectError": "Could not connect. Firewall, VPN, or wrong port.",
    "gaierror": "DNS lookup failed - check smtp_host for typos.",
    "TimeoutError": "Connection timed out. Port 587 may be blocked on this network.",
}


def main() -> int:
    cfg = mailer.load_config()
    to = sys.argv[1] if len(sys.argv) > 1 else cfg["from_email"]

    if not cfg["smtp_host"]:
        print("No smtp_host in config.json. Copy config.example.json first.")
        return 1
    if not to:
        print("No from_email in config.json and no recipient given.")
        return 1
    if not cfg["smtp_pass"]:
        print("No password found.\n"
              "  Set it with:  $env:PRIVACYLOOP_SMTP_PASS = 'your-app-password'\n"
              "  (or put it in config.json, but the env var is better)")
        return 1

    print(f"host     {cfg['smtp_host']}:{cfg['smtp_port']}  tls={cfg['use_tls']}")
    print(f"user     {cfg['smtp_user']}")
    print(f"pass     {'*' * len(cfg['smtp_pass'])} ({len(cfg['smtp_pass'])} chars)")
    print(f"sending  {cfg['from_email']} -> {to}\n")

    if len(cfg["smtp_pass"]) == 19 and " " in cfg["smtp_pass"]:
        print("  ! Your password looks like a Gmail app password with spaces still in it.")
        print("    Google displays it as 'abcd efgh ijkl mnop' but you must strip the spaces.\n")

    # Bypass dry_run - this is a deliberate live test.
    original, cfg["dry_run"] = cfg["dry_run"], False
    saved = mailer.load_config
    mailer.load_config = lambda: cfg
    try:
        ok, detail = mailer.send(9999, to, "PrivacyLoop SMTP test",
                                 "If you're reading this, sending works.\n"
                                 "You can now set \"dry_run\": false in config.json.\n")
    finally:
        mailer.load_config = saved
        cfg["dry_run"] = original

    print(detail)
    if ok:
        print("\nSUCCESS - check your inbox. Now set \"dry_run\": false in config.json.")
        return 0

    for key, hint in HINTS.items():
        if key in detail:
            print(f"\n{hint}")
            break
    return 1


if __name__ == "__main__":
    sys.exit(main())
