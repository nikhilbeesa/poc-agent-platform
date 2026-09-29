"""
Chunked LIVE-mode generation toolkit.

Why this exists: in live mode each content agent used to make ONE LLM call
that had to emit an entire document as a single JSON object (40+ BRD
sections, every FR, every screen...). A model can't reliably do that — it
gives up early and returns a token-sized sketch (11 FRs, 6 screens, 2
flows) instead of the 70+ FRs / 30 screens / 70 flows the mock generator
produces for the same idea. So live generation is now split into many small,
focused calls (plan -> per-module -> per-FR/story/screen batches -> core
sections), run in parallel, and assembled deterministically in code.

Three properties this module provides to the agents built on it:

1. Small calls: every call asks for a bounded amount of JSON, so nothing is
   cut short — and if a reply is truncated anyway, the batch is split in
   half and retried instead of failing.
2. Reuse: every generated unit remembers a fingerprint of the upstream
   input it was generated from (`_src`). On a revision pass (a "Resolve
   issues" round), a unit is only regenerated if its upstream changed or a
   validation note explicitly names it — everything else is reused
   byte-for-byte. That is what stops the resolve loop from re-rolling the
   whole package each round (the source of the "fix one thing, another
   appears" drift) and keeps a revision round to a handful of calls
   instead of hundreds.
3. Progress: long runs report what they are doing so the UI can show it.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Callable, Iterable

from llm_client import LLMTruncated, call_llm

# Parallel LLM calls per stage. Kept modest by default so a free-tier rate
# limit (HTTP 429) is absorbed by llm_client's retry/backoff rather than
# failing; raise via env var on a paid key.
MAX_PARALLEL = max(1, int(os.environ.get("LLM_MAX_PARALLEL", "4")))
JSON_ATTEMPTS = 3

_tls = threading.local()


# --------------------------------------------------------------------------
# Progress reporting
# --------------------------------------------------------------------------
def set_progress_callback(cb: Callable[[str], None] | None) -> None:
    _tls.cb = cb


def report(message: str) -> None:
    cb = getattr(_tls, "cb", None)
    if cb:
        try:
            cb(message)
        except Exception:
            pass


# --------------------------------------------------------------------------
# JSON handling
# --------------------------------------------------------------------------
def extract_json(text: str) -> Any:
    """Parse the JSON value in an LLM reply, tolerating code fences, prose
    before/after it, and trailing commas."""
    text = (text or "").strip()
    try:
        return json.loads(text)
    except Exception:
        pass
    starts = [i for i in (text.find("{"), text.find("[")) if i != -1]
    if not starts:
        raise ValueError("no JSON found in model reply")
    start = min(starts)
    end = max(text.rfind("}"), text.rfind("]"))
    if end <= start:
        raise ValueError("unterminated JSON in model reply")
    candidate = text[start:end + 1]
    try:
        return json.loads(candidate)
    except Exception:
        return json.loads(re.sub(r",\s*([}\]])", r"\1", candidate))


def salvage_array_items(partial: str, list_key: str) -> list[dict]:
    """Recovers the COMPLETE objects from a truncated `{"<list_key>": [ {...}, {...}, {...` reply
    so a cut-off long list degrades to "fewer items" instead of failing."""
    text = partial or ""
    m = re.search(rf'"{re.escape(list_key)}"\s*:\s*\[', text)
    if not m:
        return []
    dec = json.JSONDecoder()
    pos, items = m.end(), []
    while True:
        nxt = re.compile(r"[\s,]*").match(text, pos).end()
        if nxt >= len(text) or text[nxt] != "{":
            break
        try:
            obj, pos = dec.raw_decode(text, nxt)
        except json.JSONDecodeError:
            break  # the last, cut-off object
        if isinstance(obj, dict):
            items.append(obj)
    return items


def call_json(client, prompt: str, max_tokens: int = 6000, expect: type = dict) -> Any:
    """One LLM call that must return JSON of type `expect`. Re-asks (up to
    JSON_ATTEMPTS) if the reply isn't valid JSON. LLMTruncated is NOT
    swallowed here — it means the request was too big, so the caller
    should split it."""
    current = prompt
    last_err: Exception | None = None
    for _ in range(JSON_ATTEMPTS):
        raw = call_llm(client, current, max_tokens=max_tokens)  # may raise LLMTruncated
        try:
            data = extract_json(raw)
            if not isinstance(data, expect):
                raise ValueError(f"expected JSON {expect.__name__}, got {type(data).__name__}")
            return data
        except (ValueError, json.JSONDecodeError) as e:
            last_err = e
            current = prompt + (
                "\n\nYour previous reply could not be parsed as valid JSON "
                f"({e}). Reply again with ONLY the JSON object in exactly the "
                "requested shape — no commentary, no code fences."
            )
    raise RuntimeError(f"model did not return valid JSON after {JSON_ATTEMPTS} attempts: {last_err}")


# --------------------------------------------------------------------------
# Parallel execution
# --------------------------------------------------------------------------
def run_parallel(label: str, calls: list[Callable[[], Any]], workers: int | None = None) -> list[Any]:
    """Runs zero-arg callables in parallel; returns results in input order.
    Reports "label: done/total" as calls finish. If any call raises, the
    first exception is re-raised once the pool drains."""
    total = len(calls)
    if total == 0:
        return []
    results: list[Any] = [None] * total
    if total == 1:
        results[0] = calls[0]()
        report(f"{label}: 1/1")
        return results
    first_error: Exception | None = None
    done = 0
    cb = getattr(_tls, "cb", None)

    def wrap(fn):
        def inner():
            # worker threads don't inherit thread-local state, so nested
            # stages (a parallel stage that itself fans out) would otherwise
            # lose their progress reporting
            set_progress_callback(cb)
            return fn()
        return inner

    with ThreadPoolExecutor(max_workers=min(workers or MAX_PARALLEL, total)) as pool:
        futures = {pool.submit(wrap(fn)): i for i, fn in enumerate(calls)}
        for fut in as_completed(futures):
            i = futures[fut]
            try:
                results[i] = fut.result()
            except Exception as e:  # noqa: BLE001
                if first_error is None:
                    first_error = e
            done += 1
            report(f"{label}: {done}/{total}")
    if first_error is not None:
        raise first_error
    return results


# --------------------------------------------------------------------------
# Fingerprints, notes matching, small helpers
# --------------------------------------------------------------------------
def fingerprint(obj: Any) -> str:
    return hashlib.sha1(json.dumps(obj, sort_keys=True, default=str).encode()).hexdigest()[:12]


def batches(seq: list, n: int) -> list[list]:
    n = max(1, n)
    return [seq[i:i + n] for i in range(0, len(seq), n)]


def id_num(identifier: str) -> int | None:
    m = re.search(r"(\d+)\s*$", str(identifier or ""))
    return int(m.group(1)) if m else None


def make_id(prefix: str, number: int, width: int = 3) -> str:
    return f"{prefix}-{number:0{width}d}"


def mentions(notes: Iterable[str], ids: Iterable[str] = (), names: Iterable[str] = ()) -> list[str]:
    """Notes that reference any of these IDs (exact token) or names
    (case-insensitive, names shorter than 4 chars ignored)."""
    ids = [i for i in ids if i]
    names = [n.lower() for n in names if n and len(n) >= 4]
    out = []
    for note in notes:
        low = note.lower()
        if any(re.search(rf"(?<![A-Za-z0-9-]){re.escape(i)}(?![0-9])", note) for i in ids) or \
           any(n in low for n in names):
            out.append(note)
    return out


_DOC_TAG = re.compile(r"\[docs:\s*([^\]]*)\]", re.IGNORECASE)

# keywords that identify each document inside a "[docs: ...]" tag
DOC_KEYWORDS = {
    "business_analyst": ("business requirement", "brd", "business analyst"),
    "product_manager": ("user stor", "stories", "epic", "product manager"),
    "product_requirements": ("prd", "product requirement", "product overview"),
    "ux_product_flow": ("ux", "flow", "screen", "wireframe", "interaction"),
}


def notes_for_document(notes: Iterable[str], role_value: str) -> list[str]:
    """Filters validation notes down to the ones relevant to one document.
    A note tagged "[docs: ...]" is relevant only if it names this document;
    an untagged note (e.g. a coverage-matrix gap) applies to every document."""
    keywords = DOC_KEYWORDS.get(role_value, ())
    out = []
    for note in notes:
        m = _DOC_TAG.search(note)
        if not m:
            out.append(note)
            continue
        tagged = m.group(1).lower()
        if any(k in tagged for k in keywords):
            out.append(note)
    return out


# --------------------------------------------------------------------------
# Prompt fragments shared by all live agents
# --------------------------------------------------------------------------
def tag(task: str, units: Iterable[str] = ()) -> str:
    """Machine-readable header on every chunk prompt: names the sub-task and
    the unit keys requested. Ignored by the model in practice, but makes
    logs/tests unambiguous."""
    return f"[[TASK:{task}]] [[UNITS:{','.join(str(u) for u in units)}]]\n"


def idea_block(context) -> str:
    answered = "\n".join(f"- {q.text} -> {q.answer}" for q in context.discovery_questions if q.answer)
    return (
        f'Business idea: "{context.business_idea_raw}"\n'
        f"Domain: {context.domain_classification}\n"
        f"Answered discovery questions:\n{answered or '- (none)'}\n"
    )


def locked_block(context) -> str:
    decisions = getattr(context, "locked_decisions", None) or []
    if not decisions:
        return ""
    lines = "\n".join(f"- {d}" for d in decisions)
    return (
        "CONFIRMED DECISIONS FROM EARLIER RESOLUTION ROUNDS — already settled; "
        "do not reverse or re-litigate them:\n" + lines + "\n\n"
    )


def revision_block(notes: list[str], previous: Any = None) -> str:
    if not notes:
        return ""
    body = "\n".join(f"- {n}" for n in notes)
    prev = ""
    if previous is not None:
        prev = (
            "\nCurrent version of this item (keep everything not implicated by the "
            "issues exactly as written — make the smallest edit that fixes them):\n"
            + json.dumps(previous, indent=1, default=str) + "\n"
        )
    return (
        "REVISION — a validation step found these specific issues that affect this "
        "item. Your output MUST resolve every one that applies to it without "
        "introducing new inconsistencies:\n" + body + "\n" + prev + "\n"
    )


def clean(item: dict) -> dict:
    """Drops internal bookkeeping keys before an item is embedded in a prompt."""
    return {k: v for k, v in item.items() if not k.startswith("_")}


# --------------------------------------------------------------------------
# Unit generation with reuse, batching, retry and truncation splitting
# --------------------------------------------------------------------------
def generate_units(
    *,
    label: str,
    units: list[dict],
    prev_by_key: dict[str, dict],
    notes: list[str],
    hash_of: Callable[[dict], str],
    needles_of: Callable[[dict], tuple[list[str], list[str]]],
    make_prompt: Callable[[list[dict], dict[str, list[str]], dict[str, dict]], str],
    key_field: str,
    list_key: str,
    client,
    batch_size: int,
    max_tokens: int,
) -> tuple[dict[str, dict], dict[str, int]]:
    """Generates one item per unit (each unit is a dict with a "key").

    - A unit with a previous item whose fingerprint still matches and that no
      note names is REUSED untouched.
    - The rest are generated in parallel batches. The model must echo each
      unit's key in `key_field`; keys it omits are re-requested once, then
      raise.
    - If a batch reply is truncated it is split in half and retried.

    Returns ({key: item}, {"reused": n, "generated": n}).
    """
    result: dict[str, dict] = {}
    pending: list[dict] = []
    notes_by_key: dict[str, list[str]] = {}
    for u in units:
        key = u["key"]
        h = hash_of(u)
        u["_hash"] = h
        ids, names = needles_of(u)
        hit = mentions(notes, ids=ids, names=names) if notes else []
        prev = prev_by_key.get(key)
        if prev is not None and prev.get("_src") == h and not hit:
            result[key] = prev
            continue
        notes_by_key[key] = hit
        pending.append(u)
    reused = len(result)

    def gen_batch(batch: list[dict], depth: int = 0) -> dict[str, dict]:
        keys = [u["key"] for u in batch]
        try:
            data = call_json(
                client,
                make_prompt(batch, {k: notes_by_key.get(k, []) for k in keys},
                            {k: prev_by_key[k] for k in keys if k in prev_by_key}),
                max_tokens=max_tokens,
            )
        except LLMTruncated:
            if len(batch) == 1:
                raise RuntimeError(f"{label}: reply for {keys[0]} exceeded the output limit even alone")
            mid = len(batch) // 2
            out = gen_batch(batch[:mid], depth + 1)
            out.update(gen_batch(batch[mid:], depth + 1))
            return out
        got: dict[str, dict] = {}
        for item in data.get(list_key, []) or []:
            if isinstance(item, dict) and item.get(key_field) in keys:
                got[item[key_field]] = item
        missing = [u for u in batch if u["key"] not in got]
        if missing and depth < 2:
            got.update(gen_batch(missing, depth + 1))
        elif missing:
            raise RuntimeError(f"{label}: model omitted {[u['key'] for u in missing]}")
        return got

    calls = [(lambda b=b: gen_batch(b)) for b in batches(pending, batch_size)]
    for chunk_result in run_parallel(label, calls):
        for key, item in chunk_result.items():
            unit = next(u for u in pending if u["key"] == key)
            item["_src"] = unit["_hash"]
            result[key] = item
    return result, {"reused": reused, "generated": len(pending)}


# --------------------------------------------------------------------------
# Section patches (revision passes for narrative/core sections)
# --------------------------------------------------------------------------
def apply_section_patch(target: dict, changes: Any, allowed: Iterable[str]) -> list[str]:
    """Merges {"section": new_value} changes into `target`. Only allowed
    sections are accepted and the new value must have the same JSON type as
    the value it replaces (a model that answers a list-section with a string
    would corrupt the document). Returns the names actually changed."""
    if not isinstance(changes, dict):
        return []
    allowed = set(allowed)
    changed = []
    for name, value in changes.items():
        if name not in allowed:
            continue
        old = target.get(name)
        if old is not None and type(old) is not type(value):
            continue
        if value in (None, "", [], {}):
            continue
        target[name] = value
        changed.append(name)
    return changed


def as_list(value: Any) -> list:
    if isinstance(value, list):
        return value
    return [] if value in (None, "") else [value]


def as_str_list(value: Any) -> list[str]:
    return [str(v) for v in as_list(value)]


# --------------------------------------------------------------------------
# BRD depth helpers: risk scoring, Mermaid flow diagrams, key parameters
# (shared by the live and mock Business Analyst so both produce identical shapes)
# --------------------------------------------------------------------------
_LEVELS = {"low": 1, "medium": 2, "med": 2, "moderate": 2, "high": 3, "critical": 3, "very high": 3}


def _level(value: Any) -> int:
    return _LEVELS.get(str(value or "").strip().lower(), 0)


def risk_rating(likelihood: Any, severity: Any) -> tuple[str, int]:
    """Deterministic rating = likelihood x severity (each 1-3). Computed in code
    so the ranking is never a model's opinion. Unassessed -> ("Not assessed", 0)."""
    l, s = _level(likelihood), _level(severity)
    if not l or not s:
        return "Not assessed", 0
    score = l * s
    label = "High" if score >= 6 else "Medium" if score >= 3 else "Low"
    return label, score


def normalize_risks(risks: Any) -> list[dict]:
    """Keeps every risk, canonicalises likelihood/severity to Low/Medium/High,
    adds a derived rating + score and sorts highest-first."""
    out = []
    for r in as_list(risks):
        if not isinstance(r, dict) or not str(r.get("risk", "")).strip():
            continue
        r = dict(r)
        sev = r.get("severity") or (r.get("impact") if _level(r.get("impact")) else "")
        for key, val in (("likelihood", r.get("likelihood")), ("severity", sev)):
            lv = _level(val)
            r[key] = {1: "Low", 2: "Medium", 3: "High"}.get(lv, "Not assessed")
        r["rating"], r["score"] = risk_rating(r["likelihood"], r["severity"])
        for key in ("category", "owner", "trigger", "impact", "consequence", "mitigation"):
            r[key] = str(r.get(key) or "").strip()
        out.append(r)
    out.sort(key=lambda x: -x["score"])
    return out


_MERMAID_START = ("flowchart", "graph", "sequencediagram", "statediagram")


def _label(text: str) -> str:
    return re.sub(r'["\[\]{}()<>|`]', "", str(text)).strip()[:60] or "Step"


def flow_from_arrows(text: str, direction: str = "LR") -> str:
    """Deterministic fallback: 'A -> B -> C' becomes a Mermaid flowchart."""
    steps = [s for s in (p.strip() for p in re.split(r"\s*(?:->|→)\s*", str(text or ""))) if s]
    if len(steps) < 3:
        return ""
    lines = [f"flowchart {direction}"]
    for i, s in enumerate(steps):
        lines.append(f'    N{i}["{_label(s)}"]')
    lines.append("    " + " --> ".join(f"N{i}" for i in range(len(steps))))
    return "\n".join(lines)


def sanitize_mermaid(src: Any) -> str:
    """Returns cleaned Mermaid source, or "" if it doesn't look renderable."""
    text = str(src or "").strip()
    text = re.sub(r"^```(?:mermaid)?\s*|\s*```$", "", text).strip()
    lines = [ln.rstrip() for ln in text.splitlines() if ln.strip()]
    if len(lines) < 3 or not lines[0].strip().lower().startswith(_MERMAID_START):
        return ""
    if len(re.findall(r"-->|---|->>|==>", "\n".join(lines[1:]))) < 2:
        return ""
    return "\n".join(lines)


def normalize_flow_diagrams(items: Any, fallbacks: list[tuple[str, str]] = ()) -> list[dict]:
    """Valid diagrams only; fallbacks are (title, 'A -> B -> C') pairs used when
    the model returned none/invalid ones, so the BRD always has diagrams."""
    out = []
    for d in as_list(items):
        if not isinstance(d, dict):
            continue
        src = sanitize_mermaid(d.get("mermaid"))
        if src:
            out.append({"title": str(d.get("title") or "Flow").strip(),
                        "description": str(d.get("description") or "").strip(), "mermaid": src})
    if len(out) < 2:
        have = {d["title"] for d in out}
        for title, arrows in fallbacks:
            src = flow_from_arrows(arrows)
            if src and title not in have:
                out.append({"title": title, "description": "Generated from the end-to-end flow described above.", "mermaid": src})
    return out


def normalize_key_parameters(items: Any) -> list[dict]:
    out = []
    for p in as_list(items):
        if not isinstance(p, dict) or not str(p.get("parameter", "")).strip():
            continue
        status = str(p.get("status") or "").strip()
        value = str(p.get("value") or "").strip() or "TBD"
        if not status:
            status = "TBD" if value.upper().startswith("TBD") else "Proposed default"
        out.append({"parameter": str(p["parameter"]).strip(), "value": value, "status": status,
                    "related": str(p.get("related") or "").strip(), "owner": str(p.get("owner") or "").strip()})
    return out
