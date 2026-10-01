"""
System profile — expected scale, system requirements, security requirements, performance and
scalability requirements, in ONE place.

Why a shared profile: the BRD (business expectations) and the PRD (technical targets) both need to
talk about expected user volume, uptime, security and performance. If each agent invents its own
numbers the two documents disagree. So the numbers are decided once, here, from the discovery
answers, stored on ProjectContext.system_profile, and rendered by export.py into both documents
(same IDs, same targets).

Rules this module follows:
  * Numbers that come from the user's discovery answers are marked "Stated".
  * Anything the user did not answer is filled with a conservative planning default and marked
    "Assumed — confirm", and is listed in `open_questions`. Nothing is presented as a fact the
    user never gave.
  * The scale / availability numbers are computed in code (never by the LLM), so they cannot drift.
    In LIVE mode the LLM only tailors the *lists* of requirements to the product; the deterministic
    baseline fills any gap the model leaves.

Profile shape (all values JSON-serialisable):
  {
    "summary": str,
    "scale": {"rows": [{"parameter","value","basis"}], "assumptions": [str], "planning": {...numbers...}},
    "availability": {"uptime_target","allowed_downtime","rto","rpo","basis"},
    "system_requirements":      [{"id":"SYS-001","category","requirement","priority","status"}],
    "security_requirements":    [{"id":"SEC-001","category","requirement","verification","priority","status"}],
    "performance_requirements": [{"id":"PERF-001","metric","target","condition","measurement","priority","status"}],
    "scalability_requirements": [{"id":"SCL-001","requirement","target","approach","verification","priority","status"}],
    "open_questions": [str],
    "generated_by": "baseline" | "baseline+llm"
  }
"""

from __future__ import annotations

import math
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from context import ProjectContext  # noqa: E402
from logging_config import get_logger  # noqa: E402

logger = get_logger()

STATED = "Stated"
ASSUMED = "Assumed — confirm"
PROPOSED = "Proposed — confirm"                           # good-practice requirement, not something the user said
DERIVED_STATED = "Derived from stated volumes"
DERIVED_ASSUMED = "Derived from assumed volumes — confirm"


# --------------------------------------------------------------------------------------------
# Reading the discovery answers
# --------------------------------------------------------------------------------------------
def _answers(context: ProjectContext) -> dict[str, str]:
    return {q.id: (q.answer or "").strip() for q in context.discovery_questions if q.answer}


def _all_text(context: ProjectContext) -> str:
    """The idea plus the user's ANSWERS. Question wording is deliberately excluded: a question that merely
    mentions 'payment' must not make the product look like it handles payments."""
    parts = [context.business_idea_raw or ""] + [q.answer or "" for q in context.discovery_questions]
    return " ".join(parts).lower()


def _num_from(text: str) -> int | None:
    """Largest number in a free-text answer such as '10,000+', '1,000–10,000' or '50k'."""
    best = None
    for m in re.finditer(r"(\d[\d,\.]*)\s*([kKmM]?)", text or ""):
        raw = m.group(1).replace(",", "")
        try:
            val = float(raw)
        except ValueError:
            continue
        mult = {"k": 1_000, "m": 1_000_000}.get(m.group(2).lower(), 1)
        val = int(val * mult)
        if best is None or val > best:
            best = val
    return best


def _fmt(n: float | int) -> str:
    n = int(round(n))
    return f"{n:,}"


def _legacy_users_answer(context: ProjectContext) -> str:
    """A user-volume answer to an equivalent question the model asked itself (older projects
    or model-generated questions), when the required question is absent."""
    for q in context.discovery_questions:
        if q.answer and q.id != "nfr_users_12m":
            hay = f"{q.category} {q.text}".lower()
            if any(k in hay for k in ("how many users", "users do you expect", "number of users", "user volume")):
                return q.answer
    return ""


def _uptime_tier(label: str) -> tuple[str, str, str, str, str] | None:
    """(uptime target, allowed downtime per month, RTO, RPO, tier key) from the availability answer."""
    low = (label or "").lower()
    if not low or "not sure" in low:
        return None
    if "business hours" in low:
        return ("99.0% during business hours", "about 7 hours per month (outside business hours: best effort)", "8 hours", "24 hours", "low")
    if "99.95" in low or "near-zero" in low or "mission" in low:
        return ("99.95%", "about 22 minutes per month", "30 minutes", "5 minutes", "critical")
    if "99.9" in low:
        return ("99.9%", "about 43 minutes per month", "1 hour", "15 minutes", "high")
    if "99%" in low or "99 %" in low:
        return ("99.0%", "about 7 hours per month", "8 hours", "24 hours", "low")
    return None


# --------------------------------------------------------------------------------------------
# Deterministic baseline
# --------------------------------------------------------------------------------------------
def _planning_numbers(context: ProjectContext) -> dict:
    a = _answers(context)
    text = _all_text(context)
    assumptions: list[str] = []
    open_q: list[str] = []
    rows: list[dict] = []

    # ---- users ------------------------------------------------------------------------------
    users_label = a.get("nfr_users_12m") or _legacy_users_answer(context)
    users_12m = _num_from(users_label) if users_label else None
    users_stated = users_12m is not None
    if users_stated and "+" in users_label:
        users_12m *= 2   # "500,000+" is open-ended — plan with headroom above the stated floor
        assumptions.append(f"'{users_label}' is open-ended; capacity planning uses twice that figure ({_fmt(users_12m)}).")
    if users_12m is None:
        users_12m = 5_000
        assumptions.append("Expected user volume was not provided; 5,000 registered users in the first 12 months is used as a planning default.")
        open_q.append("Confirm the expected number of registered users in the first 12 months (planning default: 5,000).")
    users_36m = users_12m * 4
    rows.append({"parameter": "Registered users — first 12 months", "value": users_label if users_stated else f"about {_fmt(users_12m)}",
                 "basis": STATED if users_stated else ASSUMED})
    rows.append({"parameter": "Registered users — planning horizon (36 months)", "value": f"about {_fmt(users_36m)} (4x the 12-month figure)",
                 "basis": ASSUMED})

    # ---- peak concurrency -------------------------------------------------------------------
    peak_label = a.get("nfr_peak_concurrent", "")
    peak = None
    if peak_label and "not sure" not in peak_label.lower():
        peak = _num_from(peak_label)
    peak_stated = peak is not None
    if peak_stated and "+" in peak_label:
        peak *= 2
        assumptions.append(f"'{peak_label}' concurrent users is open-ended; capacity planning uses twice that figure ({_fmt(peak)}).")
    if peak is None:
        peak = max(25, int(math.ceil(users_12m * 0.05)))
        assumptions.append(f"Peak concurrent usage was not provided; 5% of the 12-month user base (about {_fmt(peak)}) is used as a planning default.")
        open_q.append(f"Confirm peak concurrent users (planning default: about {_fmt(peak)}).")
    planning_peak = peak * 2            # design and test headroom
    rows.append({"parameter": "Peak concurrent users (first 12 months)", "value": peak_label if peak_stated else f"about {_fmt(peak)}",
                 "basis": STATED if peak_stated else ASSUMED})
    rows.append({"parameter": "Design capacity (2x peak headroom)", "value": f"{_fmt(planning_peak)} concurrent users",
                 "basis": "Derived"})
    rps = max(5, int(math.ceil(planning_peak * 0.2)))
    rows.append({"parameter": "Sustained request rate at design capacity", "value": f"about {_fmt(rps)} requests/second (assuming about one request every 5 seconds per active user)",
                 "basis": "Derived"})

    # ---- availability -----------------------------------------------------------------------
    tier = _uptime_tier(a.get("nfr_availability", ""))
    avail_stated = tier is not None
    if tier is None:
        tier = ("99.5%", "about 3.6 hours per month", "4 hours", "1 hour", "medium")
        assumptions.append("The required availability was not provided; 99.5% is used as a planning default.")
        open_q.append("Confirm the required availability / uptime target (planning default: 99.5%).")
    availability = {"uptime_target": tier[0], "allowed_downtime": tier[1], "rto": tier[2], "rpo": tier[3],
                    "tier": tier[4], "basis": STATED if avail_stated else ASSUMED}
    rows.append({"parameter": "Availability target", "value": f"{tier[0]} (allowed downtime: {tier[1]})", "basis": availability["basis"]})
    rows.append({"parameter": "Recovery time objective (RTO) / recovery point objective (RPO)", "value": f"{tier[2]} / {tier[3]}",
                 "basis": availability["basis"]})

    # ---- geography --------------------------------------------------------------------------
    geo = a.get("nfr_geography", "")
    geo_known = bool(geo) and "not sure" not in geo.lower()
    if not geo_known:
        assumptions.append("Launch geography was not provided; a single-region deployment is assumed.")
        open_q.append("Confirm the launch geography (drives data-protection law, hosting region and latency targets).")
    rows.append({"parameter": "Launch geography", "value": geo if geo_known else "Not confirmed — single region assumed",
                 "basis": STATED if geo_known else ASSUMED})
    multi_region = geo_known and any(k in geo.lower() for k in ("several", "global"))

    # ---- data sensitivity -------------------------------------------------------------------
    sens_label = a.get("nfr_data_sensitivity", "")
    sens = {
        "personal": "personal" in sens_label.lower(),
        "payment": "payment" in sens_label.lower() or "card" in sens_label.lower(),
        "health": "health" in sens_label.lower(),
        "children": "children" in sens_label.lower(),
        "ids": "identity" in sens_label.lower() or "government" in sens_label.lower(),
        "location": "location" in sens_label.lower(),
    }
    sens_known = bool(sens_label) and "not sure" not in sens_label.lower()
    # the idea text itself can reveal payments even if the question was skipped
    if not sens["payment"] and any(k in text for k in ("payment", "checkout", "pay ", "invoice", "subscription")):
        sens["payment"] = True
    if not sens_known and not any(sens.values()):
        sens["personal"] = True          # any account-based product holds at least personal data
        assumptions.append("Data sensitivity was not provided; personal data (names, emails, phone numbers) is assumed as a minimum.")
        open_q.append("Confirm which sensitive data the product will handle (payment, health, children's, identity documents, location).")
    rows.append({"parameter": "Sensitive data handled",
                 "value": sens_label if sens_known else ", ".join(k for k, v in sens.items() if v) or "personal data (assumed)",
                 "basis": STATED if sens_known else ASSUMED})

    # ---- platform ---------------------------------------------------------------------------
    plat_text = " ".join(f"{q.answer}" for q in context.discovery_questions
                         if q.answer and any(k in f"{q.category} {q.text}".lower() for k in ("platform", "web or mobile", "web, mobile", "device")))
    is_mobile = "mobile" in plat_text.lower() or "both" in plat_text.lower() or "app store" in text
    is_web = ("web" in plat_text.lower() or "both" in plat_text.lower()) or not is_mobile
    plat_known = bool(plat_text)
    rows.append({"parameter": "Client platforms", "value": ("Web and mobile" if (is_web and is_mobile) else "Mobile app" if is_mobile else "Web application")
                 + ("" if plat_known else " (assumed)"), "basis": STATED if plat_known else ASSUMED})
    if not plat_known:
        assumptions.append("Client platform was not provided; a responsive web application is assumed.")

    return {
        "users_12m": users_12m, "users_36m": users_36m, "peak": peak, "design_peak": planning_peak, "rps": rps,
        "availability": availability, "multi_region": multi_region, "geo_known": geo_known, "geography": geo,
        "sens": sens, "is_mobile": is_mobile, "is_web": is_web, "text": text,
        "rows": rows, "assumptions": assumptions, "open_questions": open_q,
        "has_search": any(k in text for k in ("search", "discover", "browse", "filter")),
        "has_payments": sens["payment"],
        "has_ai": any(k in text for k in (" ai ", "ai-", "ai powered", "recommend", "machine learning", "chatbot", "assistant")),
        "has_realtime": any(k in text for k in ("real-time", "real time", "live chat", "chat", "messag")),
        "has_files": any(k in text for k in ("upload", "photo", "image", "document", "video", "file")),
    }


def _baseline_system(p: dict) -> list[dict]:
    av = p["availability"]
    high = av["tier"] in ("high", "critical")
    reqs = [
        ("Platform & clients", "The product shall be delivered as " + (
            "a responsive web application and native/cross-platform mobile apps sharing one backend API." if (p["is_web"] and p["is_mobile"])
            else "a mobile application backed by a versioned HTTPS API." if p["is_mobile"]
            else "a responsive web application backed by a versioned HTTPS API that a mobile client can reuse later."), "P0"),
        ("Browser & device support", "The web client shall support the latest two major versions of Chrome, Safari, Edge and Firefox" + (
            ", and the mobile apps shall support iOS 16+ and Android 10+." if p["is_mobile"] else ", on desktop, tablet and phone screen sizes."), "P0"),
        ("Hosting & infrastructure", "The product shall run on a managed cloud platform" + (
            " across at least two availability zones, with no single point of failure in the request path." if high
            else " with automated instance replacement; a single availability zone is acceptable at this availability target."), "P0"),
        ("Architecture", "The application tier shall be stateless and horizontally scalable behind a load balancer; session state shall live in a shared store, never on an application server.", "P0"),
        ("Data storage", "A managed relational database shall be the system of record" + (
            "; object storage shall hold uploaded files, served through a CDN." if p["has_files"] else "; object storage shall be used for any generated or uploaded files."), "P0"),
        ("Environments & delivery", "Separate development, staging and production environments shall exist, provisioned as code, with a CI/CD pipeline that runs automated tests and supports rollback within minutes.", "P0"),
        ("Backup & disaster recovery", f"Automated database backups with point-in-time recovery shall be kept, meeting an RPO of {av['rpo']} and an RTO of {av['rto']}; a restore shall be tested at least quarterly.", "P0"),
        ("Monitoring & observability", "Application performance monitoring, centralised structured logs, uptime checks and alerting on the availability and latency targets in this document shall be in place before launch.", "P0"),
        ("Integrations", "Every third-party integration (email/SMS" + (", payments" if p["has_payments"] else "") + ", analytics) shall be called through an adapter with timeouts, retries with back-off and a circuit breaker, so a provider outage degrades one feature instead of the whole product.", "P1"),
        ("Configuration & secrets", "Environment configuration shall be external to the code, and secrets shall be held in a managed secrets store, never in the repository or client bundles.", "P0"),
        ("Time & localisation", "All timestamps shall be stored in UTC and displayed in the user's time zone; text shall be stored as UTF-8 to allow later localisation.", "P1"),
    ]
    if p["multi_region"]:
        reqs.append(("Regions & latency", "Because users are in several countries, static content shall be served from a CDN and the deployment region(s) shall be chosen to keep round-trip latency for the main user regions within the performance targets; data-residency rules shall be confirmed per country.", "P1"))
    if p["has_realtime"]:
        reqs.append(("Real-time features", "Real-time messaging or live updates shall use a managed WebSocket/push service that scales independently of the main API.", "P1"))
    if p["has_ai"]:
        reqs.append(("AI services", "AI features shall call models through a service layer with request timeouts, usage/cost limits per user and a non-AI fallback when the model is unavailable.", "P1"))
    if p["is_mobile"]:
        reqs.append(("Mobile behaviour", "The mobile apps shall degrade gracefully on slow or lost connectivity (clear offline state, retry of queued actions where safe) and shall support OS-level push notifications.", "P1"))
    return [{"category": c, "requirement": r, "priority": pr, "status": PROPOSED} for c, r, pr in reqs]


def _baseline_security(p: dict) -> list[dict]:
    s = p["sens"]
    reqs = [
        ("Authentication", "Passwords shall be stored using a modern adaptive hash (Argon2id or bcrypt), be checked against known-breached passwords, and be at least 10 characters; login shall be rate-limited with temporary lockout after repeated failures.", "Security review and automated test of the login flow", "P0"),
        ("Authentication", "Multi-factor authentication shall be available to all users and mandatory for administrators and any user role that can access other people's data or payouts.", "Configuration review; admin login test", "P0"),
        ("Session management", "Sessions shall use short-lived tokens with rotation, secure/HttpOnly/SameSite cookies (web), server-side invalidation on logout and password change, and an idle timeout.", "Penetration test", "P0"),
        ("Authorization", "Access shall be enforced on the server for every request using role-based permissions, with object-level checks so one user can never read or change another user's records by changing an ID.", "Automated authorization tests per role; penetration test", "P0"),
        ("Encryption in transit", "All traffic shall use TLS 1.2 or higher with HSTS; plain HTTP shall redirect and internal service-to-service traffic shall also be encrypted.", "TLS scan (e.g. SSL Labs grade A)", "P0"),
        ("Encryption at rest", "Databases, backups and object storage shall be encrypted with AES-256; keys shall be managed in a key-management service and rotated at least annually.", "Cloud configuration audit", "P0"),
        ("Application security", "The product shall be protected against the OWASP Top 10: parameterised queries only, output encoding, CSRF protection, a strict Content-Security-Policy and standard security headers.", "SAST/DAST in CI; penetration test", "P0"),
        ("Abuse protection", "Public endpoints shall have rate limiting and bot/abuse protection (sign-up, login, password reset, search and any messaging or review submission).", "Load/abuse test", "P1"),
        ("Audit logging", "Security-relevant events (logins, permission changes, admin actions, data exports, deletions) shall be logged with user, time and origin, protected from modification, and retained for at least 12 months; logs shall not contain passwords, tokens or full payment details.", "Log review", "P0"),
        ("Vulnerability management", "Dependencies shall be scanned on every build, critical vulnerabilities patched within 7 days and high within 30 days, and an independent penetration test performed before launch and at least annually.", "CI report; pen-test report", "P0"),
        ("Privacy & compliance", "Applicable data-protection law for the launch geography (for example GDPR, UK GDPR, CCPA or the India DPDP Act) shall be identified before build; the product shall record consent where required and support access, correction, export and deletion of a person's data.", "Legal review; test of the data-request flows", "P0"),
        ("Data retention", "Each data category shall have a documented retention period, and expired or deleted personal data shall be removed from the live system and from backups within a defined window.", "Retention policy review", "P1"),
        ("Incident response", "A written incident-response plan shall define roles, escalation, evidence handling and breach notification to users and regulators within the legally required time.", "Tabletop exercise before launch", "P1"),
        ("Administrative access", "Production access shall be limited to named staff on a least-privilege basis, require MFA, and be logged; no shared accounts.", "Access review each quarter", "P0"),
        ("Third-party risk", "Every vendor that processes user data shall be assessed and covered by a data-processing agreement before integration.", "Vendor register review", "P1"),
    ]
    if s["payment"]:
        reqs.append(("Payment security", "Card data shall never touch or be stored on the product's servers: payments shall use a PCI DSS-compliant hosted payment provider, webhooks shall be signature-verified, and payment actions shall be idempotent to prevent double charges.", "Provider attestation; payment-flow test", "P0"))
    if s["health"]:
        reqs.append(("Health data", "Health or medical data shall be treated as restricted: field-level encryption, access limited to authorised roles, every access logged, and the regulations that apply to health data in the launch geography (for example HIPAA in the US) confirmed before build.", "Legal review; access-log audit", "P0"))
    if s["children"]:
        reqs.append(("Children's data", "Where children may use the product, verifiable parental consent, data minimisation and the child-protection rules of the launch geography (for example COPPA or the GDPR age-of-consent rules) shall be met before any data is collected.", "Legal review", "P0"))
    if s["ids"]:
        reqs.append(("Identity documents", "Identity documents shall be stored encrypted in a separate restricted store, viewable only by authorised reviewers, with every view logged and files deleted after verification unless the law requires retention.", "Access-log audit", "P0"))
    if s["location"]:
        reqs.append(("Location data", "Precise location shall be collected only with explicit consent, used only for the stated purpose, stored at the lowest precision that works, and deletable by the user.", "Consent-flow test", "P1"))
    return [{"category": c, "requirement": r, "verification": vfy, "priority": pr, "status": PROPOSED} for c, r, vfy, pr in reqs]


def _baseline_performance(p: dict) -> list[dict]:
    peak = _fmt(p["design_peak"])
    cond = f"at up to {peak} concurrent users"
    rows = [
        ("Page / screen load time (95th percentile)", "2.0 seconds or better; Largest Contentful Paint 2.5 seconds or better", "on a typical broadband or 4G connection, " + cond, "Real-user monitoring and synthetic tests", "P0"),
        ("API response time — reads (95th / 99th percentile)", "300 ms / 800 ms", cond, "APM percentile dashboards; load test", "P0"),
        ("API response time — writes (95th percentile)", "500 ms", cond, "APM percentile dashboards; load test", "P0"),
        ("Error rate", "below 0.5% of requests", cond, "APM error-rate alert; load test", "P0"),
        ("Sustained throughput", f"at least {_fmt(p['rps'])} requests per second with targets above still met", "steady load for 30 minutes", "Load test", "P0"),
        ("Background jobs and notifications", "delivered within 60 seconds of the triggering event (95th percentile)", "normal load", "Queue-latency metric", "P1"),
    ]
    if p["has_search"]:
        rows.append(("Search and filter results (95th percentile)", "1.0 second", cond, "APM; load test with representative catalogue size", "P1"))
    if p["has_payments"]:
        rows.append(("Payment step (excluding provider time)", "3 seconds or better", "normal load", "APM trace of the checkout flow", "P0"))
    if p["is_mobile"]:
        rows.append(("Mobile app cold start", "3 seconds or better on a mid-range device", "mid-range device, warm network", "Device-lab measurement", "P1"))
    if p["has_files"]:
        rows.append(("File upload", "a 10 MB file completes within 15 seconds on a typical connection", "typical 4G/broadband", "Synthetic test", "P2"))
    if p["has_ai"]:
        rows.append(("AI-generated responses", "first result shown within 5 seconds; fallback shown if not ready within 10 seconds", cond, "Latency metric per AI call", "P1"))
    return [{"metric": m, "target": t, "condition": c, "measurement": me, "priority": pr, "status": DERIVED_ASSUMED} for m, t, c, me, pr in rows]


def _baseline_scalability(p: dict) -> list[dict]:
    peak, design = _fmt(p["peak"]), _fmt(p["design_peak"])
    users36 = _fmt(p["users_36m"])
    rows = [
        ("Horizontal scaling of the application tier",
         f"Scale out automatically to hold the performance targets up to {design} concurrent users",
         "Stateless instances behind a load balancer; autoscaling on CPU (target 60%) and request latency, with a minimum of 2 instances",
         "Load test with a ramp to the design capacity", "P0"),
        ("Capacity headroom",
         f"Handle 2x the expected peak ({peak} -> {design} concurrent users) with no degradation of the performance targets",
         "Capacity model reviewed before launch and after each doubling of users",
         "Load test at 2x peak plus a spike test at 3x", "P0"),
        ("User growth",
         f"Support growth from about {_fmt(p['users_12m'])} to about {users36} registered users (36-month planning horizon) without re-architecture",
         "Database read replicas, connection pooling, caching of read-heavy data, and a documented partitioning/archiving plan before tables exceed ~50 million rows",
         "Architecture review at each 2x growth; load test on synthetic data at 36-month volume", "P1"),
        ("Data growth",
         "Storage, indexes and backups shall grow with data without slowing the main flows",
         "Indexing standards, archive of old records, lifecycle rules on object storage",
         "Query-plan review; storage-growth dashboard", "P1"),
        ("Graceful degradation under overload",
         "When capacity is exceeded, non-critical features (recommendations, analytics, exports) shall be shed first so core flows keep working",
         "Feature flags, queue-based processing for spikes (notifications, reports), request shedding with clear user messaging",
         "Chaos/overload test", "P1"),
        ("Load testing",
         "A repeatable load-test suite shall exist and run before launch and before each major release",
         "Scenarios for the main user journeys at expected, peak and 2x-peak volumes",
         "Reports archived per release", "P0"),
    ]
    if p["multi_region"]:
        rows.append(("Multi-region growth", "The design shall allow adding a second region without rewriting the data model",
                     "Region-aware configuration, CDN, and per-region data-residency rules", "Design review", "P2"))
    return [{"requirement": r, "target": t, "approach": a, "verification": v, "priority": pr, "status": DERIVED_ASSUMED} for r, t, a, v, pr in rows]


def _number(items: list[dict], prefix: str) -> list[dict]:
    for i, it in enumerate(items, start=1):
        it["id"] = f"{prefix}-{i:03d}"
    return items


def build_baseline_profile(context: ProjectContext) -> dict:
    """The deterministic profile: used as-is in mock mode and as the floor in live mode."""
    p = _planning_numbers(context)
    profile = {
        "summary": (f"Planning for up to {_fmt(p['users_12m'])} registered users in the first 12 months "
                    f"(peak up to {_fmt(p['peak'])} concurrent, designed for {_fmt(p['design_peak'])}) with a "
                    f"{p['availability']['uptime_target']} availability target."),
        "scale": {"rows": p["rows"], "assumptions": p["assumptions"],
                  "planning": {k: p[k] for k in ("users_12m", "users_36m", "peak", "design_peak", "rps")}},
        "availability": p["availability"],
        "system_requirements": _number(_baseline_system(p), "SYS"),
        "security_requirements": _number(_baseline_security(p), "SEC"),
        "performance_requirements": _number(_baseline_performance(p), "PERF"),
        "scalability_requirements": _number(_baseline_scalability(p), "SCL"),
        "open_questions": p["open_questions"],
        "generated_by": "baseline",
    }
    # statuses: a requirement is only "Stated" if the number it hangs on came from the user
    stated_scale = all(r["basis"] == STATED for r in p["rows"] if r["parameter"].startswith(("Registered users — first", "Peak concurrent")))
    for lst in ("performance_requirements", "scalability_requirements"):
        for it in profile[lst]:
            it["status"] = DERIVED_STATED if stated_scale else DERIVED_ASSUMED
    return profile


# --------------------------------------------------------------------------------------------
# LIVE mode — the model tailors the lists to this product; numbers stay deterministic
# --------------------------------------------------------------------------------------------
def _live_prompt(context: ProjectContext, profile: dict, which: str) -> str:
    import chunked as ch
    scale_lines = "\n".join(f"- {r['parameter']}: {r['value']} [{r['basis']}]" for r in profile["scale"]["rows"])
    av = profile["availability"]
    header = (
        ch.tag(f"profile.{which}") + ch.locked_block(context) +
        "You are a senior solutions architect writing the system, security, performance and scalability "
        "requirements for a product specification.\n\n" + _idea_only(context) +
        "\nFIXED planning numbers (already decided — use them exactly, never contradict or restate different figures):\n"
        + scale_lines + f"\n- Availability: {av['uptime_target']}; RTO {av['rto']}; RPO {av['rpo']}\n\n"
    )
    if which == "system_security":
        base_sys = "\n".join(f"- [{r['category']}] {r['requirement']}" for r in profile["system_requirements"])
        base_sec = "\n".join(f"- [{r['category']}] {r['requirement']}" for r in profile["security_requirements"])
        return header + (
            "Produce two lists tailored to THIS product (its domain, its users, its data, its integrations):\n"
            "1. system_requirements: platform, hosting, architecture, data storage, environments, backup/DR, monitoring, "
            "integrations, and anything specific to this product (e.g. real-time messaging, file/video handling, offline sync, AI services, "
            "maps, calendar sync). 12-20 items.\n"
            "2. security_requirements: authentication, authorization, encryption, application security, audit logging, privacy & "
            "regulatory obligations for the answered geography and data types, plus threats specific to THIS product "
            "(e.g. fake listings, review manipulation, account takeover, payment fraud, scraping). 15-25 items.\n\n"
            "Every requirement must be concrete and testable (a number, a named standard, or a checkable behaviour) — no vague words like "
            "'secure' or 'robust' on their own. Do not claim a specific regulation applies unless the answers make it clear; where the law "
            "depends on facts not given, say it must be confirmed. Cover at least these baseline topics (rewrite and specialise them, "
            "add more):\nSYSTEM BASELINE:\n" + base_sys + "\nSECURITY BASELINE:\n" + base_sec + "\n\n"
            "Priority is P0 (must have at launch), P1 or P2. For each security item add how it will be verified.\n"
            'Respond ONLY with JSON: {"system_requirements": [{"category": "...", "requirement": "...", "priority": "P0"}], '
            '"security_requirements": [{"category": "...", "requirement": "...", "verification": "...", "priority": "P0"}]}'
        )
    base_perf = "\n".join(f"- {r['metric']}: {r['target']}" for r in profile["performance_requirements"])
    base_scl = "\n".join(f"- {r['requirement']}: {r['target']}" for r in profile["scalability_requirements"])
    return header + (
        "Produce two lists tailored to THIS product:\n"
        "1. performance_requirements: response-time, throughput, error-rate and product-specific targets (the slowest or heaviest "
        "operations in THIS product — e.g. search over the catalogue, checkout, image upload, report generation, AI responses). 8-14 items. "
        "Each has a metric, a numeric target, the load condition it applies under (tie it to the fixed concurrency numbers above) and how it is measured.\n"
        "2. scalability_requirements: how the product must scale to the fixed volumes above and beyond, what grows fastest in THIS product "
        "(data, media, messages, bookings), the approach, and how it is verified. 6-10 items.\n\n"
        "Keep every number consistent with the fixed planning numbers.\n"
        "BASELINE (rewrite, specialise, add more):\nPERFORMANCE BASELINE:\n" + base_perf + "\nSCALABILITY BASELINE:\n" + base_scl + "\n\n"
        'Respond ONLY with JSON: {"performance_requirements": [{"metric": "...", "target": "...", "condition": "...", "measurement": "...", "priority": "P0"}], '
        '"scalability_requirements": [{"requirement": "...", "target": "...", "approach": "...", "verification": "...", "priority": "P0"}]}'
    )


def _idea_only(context: ProjectContext) -> str:
    """The idea and answers WITHOUT the profile block (avoids the profile quoting itself)."""
    answered = "\n".join(f"- {q.text} -> {q.answer}" for q in context.discovery_questions if q.answer)
    return (f'Business idea: "{context.business_idea_raw}"\nDomain: {context.domain_classification}\n'
            f"Answered discovery questions:\n{answered or '- (none)'}\n")


def _clean_items(raw, fields: tuple[str, ...]) -> list[dict]:
    out = []
    for it in raw or []:
        if not isinstance(it, dict):
            continue
        item = {f: str(it.get(f, "")).strip() for f in fields}
        required = "requirement" if "requirement" in fields else fields[0]
        if not item[required]:
            continue
        pr = str(it.get("priority", "P1")).strip().upper()
        item["priority"] = pr if pr in ("P0", "P1", "P2", "P3") else "P1"
        out.append(item)
    return out


def _merge_with_baseline(llm_items: list[dict], baseline: list[dict], key: str) -> list[dict]:
    """LLM items first; any baseline `key` value (e.g. category) the model did not cover is appended, so a
    thin model reply can never remove a mandatory topic."""
    covered = {str(i.get(key, "")).strip().lower() for i in llm_items}
    merged = list(llm_items)
    for b in baseline:
        if str(b.get(key, "")).strip().lower() not in covered:
            merged.append(b)
    return merged


def build_live_profile(context: ProjectContext, client) -> dict:
    import chunked as ch
    profile = build_baseline_profile(context)

    def call(which):
        def run():
            return ch.call_json(client, _live_prompt(context, profile, which), max_tokens=7000)
        return run

    ss, ps = ch.run_parallel("system profile", [call("system_security"), call("performance_scalability")])

    sys_items = _clean_items(ss.get("system_requirements"), ("category", "requirement"))
    sec_items = _clean_items(ss.get("security_requirements"), ("category", "requirement", "verification"))
    perf_items = _clean_items(ps.get("performance_requirements"), ("metric", "target", "condition", "measurement"))
    scl_items = _clean_items(ps.get("scalability_requirements"), ("requirement", "target", "approach", "verification"))

    stated_scale = profile["performance_requirements"][0]["status"] == DERIVED_STATED if profile["performance_requirements"] else False
    for it in sys_items + sec_items:
        it["status"] = PROPOSED
    for it in perf_items + scl_items:
        it["status"] = DERIVED_STATED if stated_scale else DERIVED_ASSUMED

    profile["system_requirements"] = _number(_merge_with_baseline(sys_items, profile["system_requirements"], "category"), "SYS")
    profile["security_requirements"] = _number(_merge_with_baseline(sec_items, profile["security_requirements"], "category"), "SEC")
    profile["performance_requirements"] = _number(perf_items or profile["performance_requirements"], "PERF")
    profile["scalability_requirements"] = _number(scl_items or profile["scalability_requirements"], "SCL")
    profile["generated_by"] = "baseline+llm"
    return profile


# --------------------------------------------------------------------------------------------
# Entry points
# --------------------------------------------------------------------------------------------
def ensure_profile(context: ProjectContext, client=None) -> dict:
    """Returns context.system_profile, building it first if needed (live when a client is given)."""
    if context.system_profile:
        return context.system_profile
    context.system_profile = build_live_profile(context, client) if client is not None else build_baseline_profile(context)
    return context.system_profile


def profile_or_baseline(context: ProjectContext) -> dict:
    """For export: never needs an LLM. Uses the built profile, else the deterministic baseline."""
    return context.system_profile or build_baseline_profile(context)


def prompt_block(context: ProjectContext) -> str:
    """A compact block for the live agents' prompts so every document quotes the same numbers."""
    prof = context.system_profile
    if not prof:
        return ""
    rows = "\n".join(f"- {r['parameter']}: {r['value']}" for r in prof["scale"]["rows"])
    return ("PLANNING TARGETS (single source of truth for scale, availability, performance and security — any non-functional "
            "requirement you write must be consistent with these and must not quote different numbers):\n" + rows + "\n\n")
