"""PrivacyLoop - a local data broker opt-out tracker.

Run:  python -m app.main       (from the privacyloop/ directory)
Then: http://127.0.0.1:5000
"""
from datetime import datetime, timezone
from pathlib import Path

from flask import (Flask, abort, flash, redirect, render_template, request,
                   send_file, url_for)

from app import db, letters, mailer, registry

ROOT = Path(__file__).resolve().parent.parent
app = Flask(
    __name__,
    template_folder=str(ROOT / "templates"),
    static_folder=str(ROOT / "static"),
)
app.secret_key = "local-only-not-a-secret"


@app.template_filter("humandate")
def humandate(value):
    if not value:
        return "-"
    try:
        dt = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return value
    return dt.strftime("%b %d, %Y")


@app.template_filter("daysleft")
def daysleft(value):
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return (dt - datetime.now(timezone.utc)).days


@app.context_processor
def inject_globals():
    return {"mail_ready": mailer.is_configured(), "cfg": mailer.load_config()}


# --------------------------------------------------------------------------

@app.route("/")
def dashboard():
    profile = db.get_profile()
    brokers = registry.scan(profile, db.all_status()) if profile.get("full_name") else []
    exposed = [b for b in brokers if b["likelihood"] in ("certain", "likely")]
    return render_template(
        "dashboard.html",
        profile=profile,
        stats=db.stats(),
        exposed=exposed,
        overdue=db.overdue_requests(),
        recent=db.list_requests()[:8],
        total_brokers=len(registry.load()),
    )


@app.route("/profile", methods=["GET", "POST"])
def profile_view():
    if request.method == "POST":
        data = {k: request.form.get(k, "") for k in
                ("full_name", "aliases", "emails", "phones", "addresses",
                 "birth_year", "state", "country", "reply_email")}
        data["traits"] = request.form.getlist("traits")
        db.save_profile(data)
        flash("Profile saved. Head to Brokers to see who likely has your data.", "ok")
        return redirect(url_for("brokers_view"))
    return render_template("profile.html", profile=db.get_profile(), traits=registry.TRAITS)


@app.route("/brokers")
def brokers_view():
    profile = db.get_profile()
    if not profile.get("full_name"):
        flash("Fill in your profile first - the scan needs your name at minimum.", "warn")
        return redirect(url_for("profile_view"))

    brokers = registry.scan(profile, db.all_status())
    level = request.args.get("level", "")
    category = request.args.get("category", "")
    if level:
        brokers = [b for b in brokers if b["likelihood"] == level]
    if category:
        brokers = [b for b in brokers if b["category"] == category]

    open_ids = {r["broker_id"] for r in db.list_requests()
                if r["status"] not in ("completed", "rejected")}
    law, law_name = letters.pick_law(profile)
    return render_template(
        "brokers.html",
        brokers=brokers,
        profile=profile,
        open_ids=open_ids,
        categories=registry.CATEGORY_LABELS,
        level=level,
        category=category,
        law=law,
        law_name=law_name,
    )


@app.post("/brokers/<broker_id>/status")
def broker_status(broker_id):
    db.set_status(broker_id, request.form.get("state", "unknown"),
                  request.form.get("notes", ""))
    return redirect(request.referrer or url_for("brokers_view"))


@app.route("/brokers/<broker_id>/request", methods=["GET", "POST"])
def compose(broker_id):
    broker = registry.by_id(broker_id)
    if not broker:
        abort(404)
    profile = db.get_profile()
    pkg = letters.build(broker, profile)

    if request.method == "POST":
        rid = db.create_request(
            broker_id=broker["id"],
            broker_name=broker["name"],
            action=request.form.get("action", pkg["action"]),
            law=request.form.get("law", pkg["law"]),
            channel=request.form.get("channel", pkg["channel"]),
            to_email=request.form.get("to_email", "").strip(),
            subject=request.form.get("subject", "").strip(),
            body=request.form.get("body", ""),
        )
        flash("Draft saved. Review it, then send.", "ok")
        return redirect(url_for("request_view", rid=rid))

    return render_template("compose.html", broker=broker, profile=profile, pkg=pkg)


@app.route("/requests")
def requests_view():
    return render_template(
        "requests.html",
        requests=db.list_requests(request.args.get("status") or None),
        status=request.args.get("status", ""),
    )


@app.route("/requests/<int:rid>")
def request_view(rid):
    req = db.get_request(rid)
    if not req:
        abort(404)
    broker = registry.by_id(req["broker_id"]) or {}
    return render_template("request.html", req=req, broker=broker,
                           profile=db.get_profile())


@app.post("/requests/<int:rid>/edit")
def request_edit(rid):
    db.update_request(
        rid,
        to_email=request.form.get("to_email", "").strip(),
        subject=request.form.get("subject", "").strip(),
        body=request.form.get("body", ""),
    )
    db.log_event(rid, "edited", "Draft edited")
    return redirect(url_for("request_view", rid=rid))


@app.post("/requests/<int:rid>/send")
def request_send(rid):
    req = db.get_request(rid)
    if not req:
        abort(404)
    if req["status"] != "draft":
        flash("This request has already been sent.", "warn")
        return redirect(url_for("request_view", rid=rid))
    if request.form.get("confirm") != "yes":
        flash("Tick the confirmation box before sending.", "warn")
        return redirect(url_for("request_view", rid=rid))

    really_sent, detail = mailer.send(rid, req["to_email"], req["subject"], req["body"])
    if really_sent:
        db.mark_sent(rid, req["law"], detail)
        flash(detail, "ok")
    else:
        db.log_event(rid, "send_attempt", detail)
        flash(detail, "warn")
    return redirect(url_for("request_view", rid=rid))


@app.post("/requests/<int:rid>/mark-submitted")
def request_mark_submitted(rid):
    """For form-based brokers: you filled their web form, record it here."""
    req = db.get_request(rid)
    if not req:
        abort(404)
    db.mark_sent(rid, req["law"], request.form.get("detail") or "Submitted via broker's web form")
    flash("Marked as submitted. The response clock is running.", "ok")
    return redirect(url_for("request_view", rid=rid))


@app.post("/requests/<int:rid>/status")
def request_status(rid):
    status = request.form.get("status", "")
    note = request.form.get("note", "")
    fields = {"status": status}
    if status in ("completed", "rejected"):
        fields["closed_at"] = db.now_iso()
    db.update_request(rid, **fields)
    db.log_event(rid, "status", f"{status}{': ' + note if note else ''}")
    flash(f"Marked as {status}.", "ok")
    return redirect(url_for("request_view", rid=rid))


@app.get("/requests/<int:rid>/eml")
def request_eml(rid):
    req = db.get_request(rid)
    if not req:
        abort(404)
    cfg = mailer.load_config()
    msg = mailer.build_message(req["to_email"] or "privacy@example.com",
                               req["subject"], req["body"], cfg)
    path = mailer.save_eml(rid, msg)
    return send_file(path, as_attachment=True,
                     download_name=f"{req['broker_id']}-request.eml")


@app.post("/bulk/compose")
def bulk_compose():
    """Queue drafts for every broker you've ticked."""
    profile = db.get_profile()
    ids = request.form.getlist("broker_ids")
    existing = {r["broker_id"] for r in db.list_requests()
                if r["status"] not in ("completed", "rejected")}
    made = 0
    for bid in ids:
        if bid in existing:
            continue
        broker = registry.by_id(bid)
        if not broker:
            continue
        pkg = letters.build(broker, profile)
        db.create_request(
            broker_id=broker["id"], broker_name=broker["name"],
            action=pkg["action"], law=pkg["law"], channel=pkg["channel"],
            to_email=pkg["to_email"], subject=pkg["subject"], body=pkg["body"],
        )
        made += 1
    flash(f"Queued {made} draft{'s' if made != 1 else ''}. Review each before sending.", "ok")
    return redirect(url_for("requests_view"))


if __name__ == "__main__":
    db.init()
    print("\n  PrivacyLoop running at http://127.0.0.1:5000")
    print(f"  Database: {db.DB_PATH}\n")
    app.run(host="127.0.0.1", port=5000, debug=True)
