"""Sending. Uses your own mailbox over SMTP - nothing is relayed through anyone else.

Config lives in config.json next to this package (gitignored). The password is
read from the PRIVACYLOOP_SMTP_PASS environment variable first, and only falls
back to the file if that is unset.

Set "dry_run": true and nothing leaves your machine - the app writes an .eml you
can inspect, or open in your mail client and send by hand. That is the default,
on purpose.
"""
import json
import os
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formatdate, make_msgid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config.json"
OUTBOX = ROOT / "outbox"

DEFAULTS = {
    "smtp_host": "",
    "smtp_port": 587,
    "smtp_user": "",
    "smtp_pass": "",
    "from_name": "",
    "from_email": "",
    "use_tls": True,
    "dry_run": True,
}


def load_config() -> dict:
    cfg = dict(DEFAULTS)
    if CONFIG_PATH.exists():
        try:
            cfg.update(json.loads(CONFIG_PATH.read_text(encoding="utf-8")))
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"config.json is not valid JSON: {exc}") from exc
    env_pass = os.environ.get("PRIVACYLOOP_SMTP_PASS")
    if env_pass:
        cfg["smtp_pass"] = env_pass
    return cfg


def is_configured() -> bool:
    cfg = load_config()
    return bool(cfg["smtp_host"] and cfg["from_email"])


def build_message(to_email: str, subject: str, body: str, cfg: dict) -> EmailMessage:
    msg = EmailMessage()
    msg["From"] = f'{cfg["from_name"]} <{cfg["from_email"]}>' if cfg["from_name"] else cfg["from_email"]
    msg["To"] = to_email
    msg["Subject"] = subject
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid(domain=(cfg["from_email"].split("@")[-1] or "localhost"))
    # Ask for a read receipt - weak, but occasionally proves delivery.
    msg["Disposition-Notification-To"] = cfg["from_email"]
    msg.set_content(body)
    return msg


def save_eml(request_id: int, msg: EmailMessage) -> Path:
    OUTBOX.mkdir(exist_ok=True)
    path = OUTBOX / f"request-{request_id:04d}.eml"
    path.write_bytes(bytes(msg))
    return path


def send(request_id: int, to_email: str, subject: str, body: str) -> tuple[bool, str]:
    """Returns (sent_for_real, human readable detail)."""
    cfg = load_config()
    if not to_email:
        return False, "No recipient address on this request."

    msg = build_message(to_email, subject, body, cfg)
    path = save_eml(request_id, msg)

    if cfg["dry_run"]:
        return False, f"DRY RUN - nothing was sent. Message written to {path.name}."

    if not cfg["smtp_host"]:
        return False, f"No SMTP host configured. Message written to {path.name}."

    try:
        if cfg["use_tls"]:
            with smtplib.SMTP(cfg["smtp_host"], int(cfg["smtp_port"]), timeout=30) as s:
                s.ehlo()
                s.starttls(context=ssl.create_default_context())
                s.ehlo()
                if cfg["smtp_user"]:
                    s.login(cfg["smtp_user"], cfg["smtp_pass"])
                s.send_message(msg)
        else:
            with smtplib.SMTP_SSL(cfg["smtp_host"], int(cfg["smtp_port"]),
                                  context=ssl.create_default_context(), timeout=30) as s:
                if cfg["smtp_user"]:
                    s.login(cfg["smtp_user"], cfg["smtp_pass"])
                s.send_message(msg)
    except Exception as exc:  # noqa: BLE001 - surface anything SMTP throws
        return False, f"SMTP error: {type(exc).__name__}: {exc}. Copy saved as {path.name}."

    return True, f"Sent to {to_email} via {cfg['smtp_host']}. Copy saved as {path.name}."
