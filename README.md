# PrivacyLoop

A local Incogni clone. Works out which data brokers hold a file on you, generates
statute-citing deletion requests, sends them from your own mailbox, and tracks the
legal response deadlines.

Runs entirely on your machine. No account, no server, no subscription. Your data
sits in one SQLite file you can delete.

```powershell
# Windows PowerShell - note ';' not '&&', and the leading '.\'
cd privacyloop; .\run.bat
```

Manual setup, if you'd rather not use the batch file:

```powershell
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\python -m app.main
```

Then open <http://127.0.0.1:5000>.

---

## How this actually works

Worth knowing before you trust it, because the marketing around these services is
misleading.

### There is no "scan" that finds your data

Nobody has an API that answers "which brokers have Jane Smith?" The commercial
services don't either. What they really do is maintain a broker list and fire
requests at all of them. PrivacyLoop is honest about this and uses two methods:

**1. Deterministic inference.** A broker's business model tells you who it holds.
LexisNexis Risk buys court records, DMV data and credit headers wholesale — if you
have a US credit file, they have you. That isn't a guess, so the app labels it
`certain` rather than pretending to have looked. You tick facts about yourself on
the Profile page (US resident, has a credit file, owns property, …) and each broker
declares which facts imply exposure. See `triggers` in `data/brokers.json`.

**2. One-click manual verification.** For people-search sites the app builds the
deep link into their own search — `spokeo.com/jane-q-smith` — you click, look, and
mark found / not found. Takes about ten seconds each.

**What it deliberately does not do is scrape those results.** Every people-search
site sits behind Cloudflare, their terms forbid automated access, and the effort
goes into defeating a bot check rather than into getting deleted. It's the part of
the problem with the worst effort-to-value ratio.

### The letters are the actual product

A request that says "please remove me" gets ignored. One that cites
Cal. Civ. Code § 1798.105, names a deadline, and mentions the Attorney General
lands in a compliance queue that has a legal obligation to process it. That's the
whole trick, and it's in `app/letters.py`.

The app picks your strongest statute automatically from your state or country:

| You are in | Law cited | They must respond within |
|---|---|---|
| CA, CO, CT, VA, TX, OR, + 13 more | that state's privacy act | 45 days |
| EU / EEA | GDPR Art. 17 erasure + Art. 21 objection | 30 days |
| UK | UK GDPR + DPA 2018 | 30 days |
| A US state with no law yet | CCPA + their own privacy policy | 45 days (courtesy) |

Every letter also includes the clauses that matter and that people forget:

- **Don't enrich.** The identifiers you hand over are a gift to a data broker.
  The letters explicitly forbid using them for anything but locating your record.
- **Tell me your sources.** Removal is temporary if the upstream supplier refills
  them next quarter. Ask who that is, then opt out there too.
- **Notify downstream recipients.** CCPA § 1798.105(c) and GDPR Art. 19 both
  require this, and brokers skip it unless asked.
- **Name your exemption.** Stops the vague "we're exempt" brush-off.

### Credit bureaus are a different problem

This is the nuance the consumer services gloss over. LexisNexis, CoreLogic,
ChexSystems, Early Warning and The Work Number are **consumer reporting agencies**
under the FCRA. They will not delete your file — the FCRA regulates it for
*accuracy*, not erasure, and a deletion request gets a form rejection.

Brokers flagged `"fcra": true` therefore get a completely different letter asking
for what you can actually get: a § 1681g file disclosure, a free § 1681c-1(i)
security freeze, and a § 1681b(e) prescreen opt-out — plus deletion of whatever
they hold *outside* the regulated file, which is usually a lot.

> **The Work Number** holds your salary and employment history and sells it to
> lenders and landlords. Most people have never heard of it. Freezing it is
> probably the single highest-value item on the whole list.

### Sending

Uses your own SMTP, so mail comes from you and replies come back to you. Copy
`config.example.json` to `config.json` and fill it in.

`dry_run` is **true** by default: nothing is sent, the app writes an `.eml` to
`outbox/` instead. Read one end to end before flipping it. Even with real sending
on, every send needs a confirmation checkbox, and the app never auto-sends.

Put the SMTP password in the `PRIVACYLOOP_SMTP_PASS` environment variable rather
than the file. Gmail needs an
[App Password](https://myaccount.google.com/apppasswords), not your login.

For form-only brokers the app shows your details in a copy-ready panel, opens
their form, and records that you submitted it so the deadline clock starts.

### Tracking

Deadlines are the leverage. A broker that blows the statutory window has handed
you a documented violation — the dashboard surfaces those and the request history
gives you the paper trail to attach to a complaint to your state AG or the
California Privacy Protection Agency.

---

## Operating it

### One-time setup

1. Fill in the three placeholders in `config.json` (`smtp_user`, `from_name`,
   `from_email`).

2. Generate a Gmail **App Password** at
   <https://myaccount.google.com/apppasswords> — 2FA must already be on, and your
   normal account password will not work. Google shows it as `abcd efgh ijkl mnop`;
   **strip the spaces**.

3. Put it in the environment, not the config file:

   ```powershell
   $env:PRIVACYLOOP_SMTP_PASS = 'abcdefghijklmnop'      # this session only
   [Environment]::SetEnvironmentVariable('PRIVACYLOOP_SMTP_PASS','abcdefghijklmnop','User')
   ```

   The second form persists across reboots. Open a new terminal after setting it.

4. Prove the connection works without involving a broker:

   ```powershell
   .venv\Scripts\python tools\test_smtp.py
   ```

5. Only once that lands in your inbox, set `"dry_run": false` in `config.json`.

### The send loop

Don't fire everything at once. Twenty-odd near-identical emails leaving a personal
Gmail inside a minute gets filed as spam on the way out by Google and on the way in
by the brokers' own filters. Send in waves over a week or two:

```powershell
.venv\Scripts\python tools\send_batch.py --limit 5            # preview
.venv\Scripts\python tools\send_batch.py --limit 5 --yes      # send, 45s apart
```

Run it once a day until the queue drains. Form-only brokers are skipped — do those
in the web UI, where the app shows a copy-ready panel, opens their form, and
records the submission so the deadline clock starts.

### Handling the replies

Make a Gmail filter now, before anything goes out — label anything matching
`"personal information" OR "opt-out" OR "CCPA" OR "deletion request"` so responses
don't scatter through your inbox. Then log each one in the app so the audit trail
stays intact.

Expect four kinds of reply:

- **Confirmation.** Mark the request `completed`.
- **Identity verification.** Normal and usually legitimate — they're required to
  verify before deleting. **Send the minimum.** A redacted utility bill or a
  driver's licence with the number blacked out is nearly always enough. *Never*
  send a full SSN, an unredacted ID, or a selfie holding your licence. A broker
  asking for more identity than they claim to hold is a reason to refuse and say
  so in writing.
- **"We can't find you."** Often true if you only gave a current address. Add past
  addresses and maiden names to your profile, regenerate, and resend.
- **Silence.** The most common outcome. The dashboard flags these the moment the
  statutory window lapses, which is the point at which you have a documented
  violation to attach to a complaint.

### Keeping it current

- **Re-verify every 3–6 months.** People-search sites refill from upstream
  suppliers, so removal is not permanent. That recurring sweep is most of what an
  ongoing subscription actually buys you.
- `privacyloop.db` holds everything — your profile, every letter, every deadline.
  Back it up. It's also the only copy of your evidence trail.
- Run `tools/verify_links.py` before each new wave; opt-out URLs rot constantly.

## Growing the broker list

37 brokers ship in `data/brokers.json`, chosen for impact. That's a starting point,
not the universe — there are several hundred.

**The best source is free and official.** California's Delete Act requires every
broker doing business there to register with the CPPA and publish its opt-out URL
and contact email. That public list is the same one the paid services work from.

```bash
# download the CSV from https://cppa.ca.gov/data_broker_registry/
python tools/import_ca_registry.py ~/Downloads/data-broker-registry.csv
```

Opt-out URLs rot constantly, so check them before a big send:

```bash
python tools/verify_links.py          # report only
python tools/verify_links.py --fix    # mark the healthy ones verified
```

Every seeded entry is `"verified": false` until you confirm it yourself. A `BLOCK`
result means Cloudflare refused the checker, not that the link is dead — open
those in a browser.

## Layout

```
app/letters.py     the legal templates - the part that matters
app/registry.py    exposure inference and lookup-URL building
app/db.py          SQLite schema, status tracking, deadline math
app/mailer.py      SMTP with dry-run default
data/brokers.json  the broker catalogue
tools/             CA registry import, link verification
```

## Realistic expectations

- Good brokers comply in 2–6 weeks. Some need a second letter. Some ignore you
  until you mention the regulator.
- **Removal is not permanent.** People-search sites refill from upstream suppliers.
  Re-run the verification pass every 3–6 months; that recurring check is most of
  what an ongoing subscription buys you.
- The highest-leverage items aren't the people-search sites everyone focuses on.
  They're The Work Number, LexisNexis, Acxiom, and `optoutprescreen.com`.

## Legal note

The statutes cited are real and current as of 2026, but this is a personal tool
and **not legal advice**. You're responsible for what you send. Only ever submit
requests about yourself — filing on someone else's behalf without authorisation is
its own legal problem.
