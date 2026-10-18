"""Conservative semantic checks for AI-authored filing claims.

The module is deliberately deterministic: it does not classify the filing with another
model. It holds claims when their wording contradicts the cited evidence.
"""
from __future__ import annotations

import re
import unicodedata
from urllib.parse import urlparse


def _norm(value: object) -> str:
    value = unicodedata.normalize("NFKC", str(value or ""))
    return re.sub(r"\\s+", " ", value).strip().casefold()


_NEGATIVE_EVENT = re.compile(
    r"\\b(?:cancel(?:led|ed|lation)?|terminat(?:ed|ion)|withdraw(?:n|al)?|rescinded|"
    r"revoked|rejected|not awarded|not selected|did not receive|no order was received)\\b", re.I)
_POSITIVE_EVENT = re.compile(
    r"\\b(?:wins?|won|awarded|secures?|secured|bags?|bagged|receives?|received|"
    r"approved|approves|completes?|completed|acquires?|acquired|launches?|launched|"
    r"commences?|commenced|starts?|started)\\b", re.I)
_CANCEL_WORD = re.compile(r"\\b(?:cancel|terminat|withdraw|rescind|revoke|reject|not awarded|not selected)\\w*\\b", re.I)
_APPROVED = re.compile(r"\\b(?:approved|approves|approval granted|sanctioned|authori[sz]ed|cleared)\\b", re.I)
_PENDING = re.compile(
    r"\\b(?:proposed|recommend(?:ed|ation)?|in-principle|deferred|considered|"
    r"subject to (?:shareholder |regulatory |government |board )?approval|"
    r"seeks? approval|will seek approval|awaiting approval)\\b", re.I)
_COMPLETED = re.compile(r"\\b(?:completed|closed|concluded|has acquired|acquired|commenced operations)\\b", re.I)
_RISE = re.compile(r"\\b(?:rose|ris(?:e|es|ing)|increas(?:e|ed|es|ing)|grew|growth|higher|up)\\b", re.I)
_FALL = re.compile(r"\\b(?:fell|fall(?:s|en|ing)?|declin(?:e|ed|es|ing)|decreas(?:e|ed|es|ing)|lower|down|reduction)\\b", re.I)
_GUIDANCE = re.compile(r"\\b(?:target|guid(?:e|ance|ed)|expect(?:s|ed)?|aim(?:s|ed)?|outlook|plan(?:s|ned)?|intend(?:s|ed)?|will|commit(?:s|ted)?)\\b", re.I)
_RESULT_VERB = re.compile(r"\\b(?:met|achieved|exceeded|missed|fell short of|beat)\\b", re.I)
_PERCENT = re.compile(r"(?<![\\w.])([+-]?\\d+(?:,\\d{3})*(?:\\.\\d+)?)\\s*%")
_METRIC = re.compile(r"\\b(ebitda|ebit|operating margin|net interest margin|gross margin|net margin|revenue|sales|pat|net profit|profit|attrition|order book)\\b", re.I)
_GENERIC_CAPITALISED = {
    "annual general meeting", "board meeting", "financial results", "revenue from operations",
    "net profit", "profit after tax", "operating margin", "ebitda margin", "credit rating",
    "high court", "supreme court", "national company law tribunal", "income tax", "gst council",
    "reserve bank of india", "securities and exchange board of india", "india ratings",
    "care ratings", "crisil ratings", "icra ratings", "standalone results", "consolidated results",
}


def semantic_reason(text: object, quote: object, category: str = "", doc: str = "",
                    issuer_names=()) -> str | None:
    """Return a hold reason when the claim's action, status, direction or named party conflicts with its quote."""
    claim, proof = str(text or "").strip(), str(quote or "").strip()
    if not claim or not proof:
        return None
    c, q = claim.casefold(), proof.casefold()

    if _NEGATIVE_EVENT.search(proof) and _POSITIVE_EVENT.search(claim) and not _CANCEL_WORD.search(claim):
        return "the quote describes a cancellation, termination, withdrawal or rejection but the claim states a positive event"
    if _POSITIVE_EVENT.search(proof) and _CANCEL_WORD.search(claim) and not _NEGATIVE_EVENT.search(proof):
        return "the claim says the event was cancelled or terminated but its quote does not support that status"

    if re.search(r"\\b(?:approved|approves|completed|completed the acquisition|closed the deal|commenced operations)\\b", c):
        if _PENDING.search(proof) and not _APPROVED.search(proof):
            return "the claim upgrades a proposal, recommendation or pending approval to an approved/completed action"
    if _COMPLETED.search(claim) and re.search(r"\\b(?:subject to|awaiting|pending|will seek|seeks)\\b.{0,45}\\b(?:approval|clearance|consent)\\b", proof, re.I):
        if not _COMPLETED.search(proof):
            return "the claim says the transaction is completed while its quote says an approval or condition is pending"

    if _RISE.search(claim) and _FALL.search(proof) and not _RISE.search(proof):
        return "the claim says the measure rose, but its quote describes a fall or reduction"
    if _FALL.search(claim) and _RISE.search(proof) and not _FALL.search(proof):
        return "the claim says the measure fell, but its quote describes a rise or increase"

    # Proper-name phrases in the claim must be in the quoted evidence, unless they are the listed issuer itself.
    issuer = {_norm(n) for n in issuer_names if str(n or "").strip()}
    issuer |= {re.sub(r"\\b(?:limited|ltd|private|pvt)\\b\\.?$", "", x).strip() for x in list(issuer)}
    for match in re.finditer(r"\\b[A-Z][a-z]+(?:\\s+[A-Z][a-z]+){1,3}\\b", claim):
        phrase = match.group(0)
        pn = _norm(phrase)
        if pn in _GENERIC_CAPITALISED or pn in issuer or any(pn in name or name in pn for name in issuer if name):
            continue
        if pn not in _norm(proof):
            return f'the named party "{phrase}" is not present in the claim\'s supporting quote'
    return None


def _contains(haystack: str, needle: str) -> bool:
    h, n = _norm(haystack), _norm(needle)
    return bool(n) and n in h


def _guidance_comparison_reason(text: str, evidence: list[dict]) -> str | None:
    """Require both historical guidance and current evidence; check simple percentage margin comparisons arithmetically."""
    if not _RESULT_VERB.search(text):
        return None
    memory_quotes = [str(e.get("quote") or "") for e in evidence if e.get("source") == "company_memory"]
    current_quotes = [str(e.get("quote") or "") for e in evidence if e.get("source") == "current_filing"]
    if not memory_quotes or not current_quotes:
        return "a claim that guidance was met or missed needs both prior guidance and current-period evidence"
    prior = " ".join(memory_quotes)
    current = " ".join(current_quotes)
    pm, cm = _METRIC.search(prior), _METRIC.search(current)
    if not pm or not cm or pm.group(1).casefold() != cm.group(1).casefold():
        return "the prior guidance and current result do not identify the same measure"
    if not _GUIDANCE.search(prior):
        return "the historical evidence does not establish a forward-looking target or guidance"
    # Do not infer direction for a percentage that is not clearly an EBITDA/operating margin target.
    if not re.search(r"\\b(?:ebitda|operating|gross|net interest|net)\\s+margin\\b", prior, re.I):
        return None
    pcts = [float(x.replace(",", "")) for x in _PERCENT.findall(prior)]
    ccts = [float(x.replace(",", "")) for x in _PERCENT.findall(current)]
    if not pcts or not ccts:
        return "the target comparison lacks a quoted percentage for both the target and the actual result"
    target, actual = pcts[-1], ccts[-1]
    t = text.casefold()
    if ("missed" in t or "fell short" in t) and actual >= target:
        return "the claim says the margin target was missed, but the quoted actual is at or above the target"
    if ("met" in t or "achieved" in t or "beat" in t) and actual < target:
        return "the claim says the margin target was met, but the quoted actual is below the target"
    if "exceeded" in t and actual <= target:
        return "the claim says the target was exceeded, but the quoted actual does not exceed it"
    return None


def validate_narrative(items, doc: str, memory: str, number_check, current_url: str | None = None) -> list[dict]:
    """Validate each narrative claim against verbatim current-filing or persistent-memory evidence."""
    if not isinstance(items, list):
        return []
    out = []
    for raw in items[:5]:
        if not isinstance(raw, dict) or not str(raw.get("text") or "").strip():
            continue
        text = str(raw["text"]).strip()
        raw_evidence = raw.get("evidence") if isinstance(raw.get("evidence"), list) else []
        evidence, errors = [], []
        for item in raw_evidence[:4]:
            if not isinstance(item, dict):
                continue
            source = str(item.get("source") or "").strip()
            quote = str(item.get("quote") or "").strip()
            if source not in ("current_filing", "company_memory") or not quote:
                errors.append("evidence source or quote is missing")
                continue
            corpus = doc if source == "current_filing" else memory
            if not _contains(corpus, quote):
                errors.append("the quoted evidence is not found in its stated source")
                continue
            source_url = current_url if source == "current_filing" else None
            if source == "company_memory":
                # Only reuse a URL already present on the exact memory line containing the evidence.
                line = next((ln for ln in str(memory or "").splitlines() if _contains(ln, quote)), "")
                m = re.search(r"https?://[^\\s)]+", line)
                source_url = m.group(0).rstrip(".,") if m else None
            evidence.append({"source": source, "quote": quote, "source_url": source_url})
        if not evidence:
            errors.append("no verifiable source quote")
        quotes = [e["quote"] for e in evidence]
        if evidence and not number_check(text, quotes):
            errors.append("a number in the narrative is not backed by its cited evidence")
        if evidence:
            why = semantic_reason(text, " ".join(quotes))
            if why:
                errors.append(why)
            compare_why = _guidance_comparison_reason(text, evidence)
            if compare_why:
                errors.append(compare_why)
        out.append({"text": text, "evidence": evidence, "shown": not errors,
                    "reason": "; ".join(dict.fromkeys(errors)) or None})
    return out
