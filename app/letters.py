"""Request letter generation.

A deletion request that cites a statute and a deadline gets processed by a
compliance queue. One that says "please remove me" gets ignored. That is
essentially the entire trick behind the paid services.

NOT LEGAL ADVICE. These templates track the cited statutes as of 2026 but you
are responsible for what you send.
"""
from datetime import datetime, timedelta, timezone

# State privacy laws with a consumer deletion right. Add rows as more take effect.
STATE_LAWS = {
    "CA": ("CCPA", "the California Consumer Privacy Act as amended by the CPRA (Cal. Civ. Code §§ 1798.100 et seq.)"),
    "CO": ("CPA", "the Colorado Privacy Act (C.R.S. §§ 6-1-1301 et seq.)"),
    "CT": ("CTDPA", "the Connecticut Data Privacy Act (Conn. Gen. Stat. §§ 42-515 et seq.)"),
    "VA": ("VCDPA", "the Virginia Consumer Data Protection Act (Va. Code §§ 59.1-575 et seq.)"),
    "UT": ("UCPA", "the Utah Consumer Privacy Act (Utah Code §§ 13-61-101 et seq.)"),
    "TX": ("TDPSA", "the Texas Data Privacy and Security Act (Tex. Bus. & Com. Code ch. 541)"),
    "OR": ("OCPA", "the Oregon Consumer Privacy Act (ORS 646A.570 et seq.)"),
    "MT": ("MTCDPA", "the Montana Consumer Data Privacy Act (Mont. Code §§ 30-14-2801 et seq.)"),
    "DE": ("DPDPA", "the Delaware Personal Data Privacy Act"),
    "NJ": ("NJDPA", "the New Jersey Data Privacy Act"),
    "NH": ("NHPA", "the New Hampshire Privacy Act"),
    "NE": ("NDPA", "the Nebraska Data Privacy Act"),
    "MN": ("MCDPA", "the Minnesota Consumer Data Privacy Act"),
    "MD": ("MODPA", "the Maryland Online Data Privacy Act"),
    "IA": ("ICDPA", "the Iowa Consumer Data Protection Act"),
    "IN": ("INCDPA", "the Indiana Consumer Data Protection Act"),
    "TN": ("TIPA", "the Tennessee Information Protection Act"),
    "KY": ("KCDPA", "the Kentucky Consumer Data Protection Act"),
    "RI": ("RIDTPPA", "the Rhode Island Data Transparency and Privacy Protection Act"),
}

EU_COUNTRIES = {
    "AT", "BE", "BG", "HR", "CY", "CZ", "DK", "EE", "FI", "FR", "DE", "GR",
    "HU", "IE", "IT", "LV", "LT", "LU", "MT", "NL", "PL", "PT", "RO", "SK",
    "SI", "ES", "SE", "IS", "LI", "NO",
}

WINDOW_DAYS = {"GDPR": 30, "UK-GDPR": 30}


def pick_law(profile: dict) -> tuple[str, str]:
    """Choose the strongest statute the user can actually invoke."""
    country = (profile.get("country") or "US").upper()
    state = (profile.get("state") or "").upper()[:2]

    if country in EU_COUNTRIES:
        return "GDPR", "the EU General Data Protection Regulation (Regulation (EU) 2016/679)"
    if country in ("GB", "UK"):
        return "UK-GDPR", "the UK GDPR and the Data Protection Act 2018"
    if country == "US" and state in STATE_LAWS:
        return STATE_LAWS[state]
    if country == "US":
        # No state law yet. Cite CCPA anyway - large brokers apply it nationally
        # rather than maintain two pipelines, and many will honour it.
        return "NONE", (
            "your published privacy policy and the California Consumer Privacy Act, "
            "which many data brokers apply to all US residents as a matter of policy"
        )
    return "NONE", "your published privacy policy and applicable data protection law"


def _identifiers(profile: dict) -> str:
    def block(label, raw, note=""):
        vals = [v.strip() for v in (raw or "").splitlines() if v.strip()]
        if not vals:
            return ""
        joined = "\n".join(f"    - {v}" for v in vals)
        return f"  {label}{note}:\n{joined}\n"

    out = f"  Full name: {profile.get('full_name', '')}\n"
    out += block("Other names used", profile.get("aliases"))
    out += block("Email addresses", profile.get("emails"))
    out += block("Phone numbers", profile.get("phones"))
    out += block("Addresses", profile.get("addresses"), " (current and previous)")
    if profile.get("birth_year"):
        out += f"  Year of birth: {profile['birth_year']}\n"
    return out


def _deadline(law: str) -> tuple[str, int]:
    days = WINDOW_DAYS.get(law, 45)
    when = datetime.now(timezone.utc) + timedelta(days=days)
    return when.strftime("%B %d, %Y"), days


# --------------------------------------------------------------------------
# Templates
# --------------------------------------------------------------------------

def _deletion_letter(broker, profile, law, law_name):
    deadline, days = _deadline(law)
    gdpr = law in ("GDPR", "UK-GDPR")

    rights = (
        "  1. ERASURE of all personal data you hold concerning me (Art. 17 GDPR).\n"
        "  2. An OBJECTION under Art. 21 GDPR to any processing for direct marketing\n"
        "     purposes, which is absolute and takes effect immediately.\n"
        "  3. ACCESS under Art. 15 GDPR: confirmation of what you held, its sources,\n"
        "     and every recipient or category of recipient it was disclosed to.\n"
        "  4. Notification of this erasure to each third party to whom you disclosed\n"
        "     my data, per Art. 19 GDPR.\n"
        if gdpr else
        "  1. DELETE all personal information you have collected about me, and direct\n"
        "     your service providers and contractors to do the same.\n"
        "  2. STOP SELLING AND SHARING my personal information to or with any third\n"
        "     party, including for cross-context behavioural advertising.\n"
        "  3. Tell me what you held: the categories of personal information collected,\n"
        "     the sources it came from, the business purpose, and the categories of\n"
        "     third parties you disclosed it to.\n"
        "  4. Notify every third party to whom you sold or shared my information that\n"
        "     it must also be deleted.\n"
    )

    body = f"""To the Privacy Officer at {broker['name']},

I am a resident of {profile.get('state') or profile.get('country') or 'the United States'} exercising my rights under {law_name}.

I am the individual identified below. I am submitting this request on my own
behalf, not through an authorised agent.

IDENTIFIERS FOR MATCHING
{_identifiers(profile)}
WHAT I AM REQUESTING

{rights}
  5. Confirm completion to me in writing at {profile.get('reply_email') or '(see sender address)'}.

LIMITS ON THIS REQUEST

The identifiers above are provided solely so that you can locate my records.
Do not use them to enrich, update, or append to any profile, do not add them to
any marketing or suppression list beyond what is strictly necessary to honour
this request, and do not retain them for any other purpose.

If you maintain a suppression list to prevent my data being re-collected, please
add me to it and say so in your reply.

If you claim an exemption for any part of this request, identify the specific
statutory provision you are relying on and the specific data it covers.

DEADLINE

{law_name.split('(')[0].strip() if law != 'NONE' else 'Applicable law'} requires a substantive response within {days} days. I therefore expect
your confirmation on or before {deadline}.

If I do not receive one I will file a complaint with {'my supervisory authority under Art. 77 GDPR' if gdpr else 'the California Privacy Protection Agency and my state Attorney General'}.

Regards,
{profile.get('full_name', '')}
{profile.get('reply_email', '')}
"""
    subject = (
        f"{'GDPR Art. 17 Erasure Request' if gdpr else 'Consumer Request to Delete Personal Information'}"
        f" - {profile.get('full_name', '')}"
    )
    return subject, body


def _suppression_letter(broker, profile, law, law_name):
    deadline, days = _deadline(law)
    body = f"""To {broker['name']},

I am requesting the removal of my personal information from {broker['domain']}
and from every site, API, and downstream product you operate or supply.

This request is made under {law_name}.

RECORDS TO REMOVE
{_identifiers(profile)}
This covers any listing containing my name, current or former addresses, phone
numbers, email addresses, age or date of birth, relatives and associates,
property records, or any profile assembled from them.

I ALSO REQUEST THAT YOU

  1. Suppress these identifiers so that the listing does not reappear the next
     time you refresh from your upstream sources.
  2. Tell me which upstream sources supplied this record, so that I can approach
     them directly.
  3. Remove any cached or syndicated copies you control, and de-index the URLs
     with the major search engines.
  4. Confirm removal in writing to {profile.get('reply_email') or '(sender address)'}.

Do not use the identifiers above for any purpose other than locating and
removing these records.

Please complete this within {days} days, i.e. on or before {deadline}.

Regards,
{profile.get('full_name', '')}
{profile.get('reply_email', '')}
"""
    return f"Opt-Out / Record Removal Request - {profile.get('full_name', '')}", body


def _fcra_letter(broker, profile, law, law_name):
    """Consumer reporting agencies work differently - freeze and disclose, not delete."""
    body = f"""To the Consumer Relations Department at {broker['name']},

I understand that {broker['name']} operates as a consumer reporting agency under
the Fair Credit Reporting Act, 15 U.S.C. § 1681 et seq. I am therefore making
the following requests, which are the ones available to me in that context.

CONSUMER IDENTIFIERS
{_identifiers(profile)}
MY REQUESTS

  1. FILE DISCLOSURE - Under 15 U.S.C. § 1681g, provide me with all information
     in my file at the time of the request, the sources of that information, and
     the identity of each person who procured a consumer report about me in the
     past two years for employment purposes, or one year for any other purpose.
     Include every specialty report or product you maintain about me, not only
     your primary one.

  2. SECURITY FREEZE - Under 15 U.S.C. § 1681c-1(i), place a security freeze on
     my file at no charge, and confirm the date it takes effect.

  3. OPT OUT OF PRESCREENED OFFERS - Under 15 U.S.C. § 1681b(e), exclude me from
     all lists provided for firm offers of credit or insurance, permanently.

  4. MARKETING DATA - To the extent you hold data about me OUTSIDE your FCRA-
     regulated file - for marketing, identity resolution, or analytics products -
     that data is not covered by the FCRA's accuracy regime, and I request its
     deletion under:

         {law_name}

     Please state clearly which of my data you are treating as FCRA-regulated
     and which you are not.

Please respond in writing to {profile.get('reply_email') or '(sender address)'}.

Regards,
{profile.get('full_name', '')}
{profile.get('reply_email', '')}
"""
    return f"FCRA File Disclosure, Security Freeze and Opt-Out Request - {profile.get('full_name', '')}", body


def _sale_optout_letter(broker, profile, law, law_name):
    deadline, days = _deadline(law)
    body = f"""To the Privacy Officer at {broker['name']},

Under {law_name}, I am directing you to STOP SELLING AND SHARING my personal
information with any third party, including for cross-context behavioural
advertising or targeted advertising.

IDENTIFIERS
{_identifiers(profile)}
Please also:

  1. Confirm the date this takes effect.
  2. Notify any third party to whom you have already sold or shared my data in
     the preceding 90 days that they must stop as well.
  3. Do not ask me to create an account in order to exercise this right.

Please confirm within {days} days, on or before {deadline}, at
{profile.get('reply_email') or '(sender address)'}.

Regards,
{profile.get('full_name', '')}
"""
    return f"Request to Opt Out of Sale/Sharing - {profile.get('full_name', '')}", body


BUILDERS = {
    "deletion": _deletion_letter,
    "suppression": _suppression_letter,
    "freeze": _fcra_letter,
    "sale_optout": _sale_optout_letter,
    "prescreen_optout": _sale_optout_letter,
}


def build(broker: dict, profile: dict) -> dict:
    """Produce the request package for one broker."""
    law, law_name = pick_law(profile)
    action = broker.get("action", "deletion")
    if broker.get("fcra"):
        action = "freeze"

    subject, body = BUILDERS.get(action, _deletion_letter)(broker, profile, law, law_name)
    return {
        "law": law,
        "action": action,
        "subject": subject,
        "body": body,
        "to_email": broker.get("privacy_email") or "",
        "channel": "email" if broker.get("privacy_email") else "form",
    }
