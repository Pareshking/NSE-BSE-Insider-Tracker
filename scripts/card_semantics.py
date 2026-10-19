"""Conservative semantic checks for AI-authored filing claims.

The module is deliberately deterministic: it does not classify the filing with another
model. It holds claims when their wording contradicts the cited evidence.
"""
from __future__ import annotations

import re
import unicodedata


def _norm(value: object) -> str:
    value = unicodedata.normalize("NFKC", str(value or ""))
    return re.sub(r"\s+", " ", value).strip().casefold()


_NEGATIVE_EVENT = re.compile(
    r"\b(?:cancel(?:led|ed|lation)?|terminat(?:ed|ion)|withdraw(?:n|al)?|rescinded|"
    r"revoked|rejected|not awarded|not selected|did not receive|no order was received|"
    r"not approved|did not approve|approval not granted|not completed|did not complete|"
    r"not launched|did not launch|not commenced|did not commence)\b", re.I)
_NEGATED_ACTION = re.compile(
    r"\b(?:not|never|no|did not|does not|has not|have not|was not|were not|is not|isn't|wasn't|weren't)\b"
    r".{0,35}\b(?:win|award|approve|complete|acquire|receive|launch|commence|start|pay|increase|rise|grow)\w*\b", re.I)
_POSITIVE_EVENT = re.compile(
    r"\b(?:wins?|won|awarded|secures?|secured|bags?|bagged|receives?|received|"
    r"approved|approves|completes?|completed|acquires?|acquired|launches?|launched|"
    r"commences?|commenced|starts?|started)\b", re.I)
_CANCEL_WORD = re.compile(r"\b(?:cancel|terminat|withdraw|rescind|revoke|reject|not awarded|not selected)\w*\b", re.I)
_APPROVED = re.compile(r"\b(?:approved|approves|approval granted|sanctioned|authori[sz]ed|cleared)\b", re.I)
_PENDING = re.compile(
    r"\b(?:proposed|recommend(?:ed|ation)?|in-principle|deferred|considered|"
    r"subject to (?:shareholder |regulatory |government |board )?approval|"
    r"seeks? approval|will seek approval|awaiting approval)\b", re.I)
_COMPLETED = re.compile(r"\b(?:completed|closed|concluded|has acquired|acquired|commenced operations)\b", re.I)
_RISE = re.compile(r"\b(?:rose|ris(?:e|es|ing)|increas(?:e|ed|es|ing)|grew|growth|higher|up)\b", re.I)
_FALL = re.compile(r"\b(?:fell|fall(?:s|en|ing)?|declin(?:e|ed|es|ing)|decreas(?:e|ed|es|ing)|lower|down|reduction)\b", re.I)
_GUIDANCE = re.compile(r"\b(?:targets?|targeted|targeting|guid(?:e|ance|ed)|expect(?:s|ed)?|aim(?:s|ed)?|outlook|plan(?:s|ned)?|intend(?:s|ed)?|will|commit(?:s|ted)?)\b", re.I)
_NO_GUIDANCE = re.compile(r"(?:do not|don't|doesn't|does not)\s+(?:provide|give)\b.{0,80}\bguidance\b", re.I)
_RESULT_VERB = re.compile(r"\b(?:met|achieved|exceeded|missed|fell short of|beat)\b", re.I)
_PERCENT = re.compile(r"(?<![\w.])([+-]?\d+(?:,\d{3})*(?:\.\d+)?)\s*%")
_METRIC = re.compile(r"\b(ebitda|ebit|operating margin|net interest margin|gross margin|net margin|revenue|sales|pat|net profit|profit|attrition|order book)\b", re.I)
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

    # A filing-specific exemption is not a blanket exemption from the underlying
    # governance obligation. Keep the legal/reporting scope in the headline.
    broad_governance_exemption = re.search(
        r"\b(?:exempt\s+from|non[- ]applicability\s+of|non[- ]applicable\s+to|not\s+applicable\s+to)\s+corporate\s+governance\b",
        c,
    ) or re.search(r"\bexemption\s+applies\b", c) or re.search(r"\bcorporate\s+governance\s+exemption\b", c)
    claim_scoped = bool(
        re.search(r"\bcorporate\s+governance\s+report(?:ing)?\b", c)
        or (re.search(r"\bprovisions?\b", c) and re.search(r"\breg(?:ulation)?\.?\s*27\b", c))
    )
    # The headline's own quote can be a narrow supporting fragment (e.g. SME
    # listing status), while the same filing establishes that the exemption is
    # only about the Regulation 27 report. Use the full source document to detect
    # that scope; never let a partial headline quote hide a scope mismatch.
    scope_proof = f"{proof}\n{doc}"
    scope_proof_folded = scope_proof.casefold()
    evidence_is_specific = bool(
        re.search(r"\bcorporate\s+governance\s+report\b", scope_proof_folded)
        or re.search(r"\breg(?:ulation)?\.?\s*27\b", scope_proof_folded)
    )
    if broad_governance_exemption and evidence_is_specific and not claim_scoped:
        return "the claim drops the specific Corporate Governance Report/Regulation 27 scope and overstates the exemption as covering corporate governance generally"

    # A causal explanation is a separate claim. Do not show it merely because the
    # headline number or the event itself is supported by a different part of the quote.
    causal = re.search(
        r"\b(?:driven\s+by|due\s+to|because\s+of|attributed\s+to|reflecting|led\s+by|supported\s+by)\s+([^.;:]{4,140})",
        claim, re.I,
    )
    if causal:
        stop = {"about", "after", "also", "among", "and", "are", "been", "being", "because", "by",
                "due", "for", "from", "have", "into", "its", "more", "not", "of", "on", "over",
                "that", "the", "their", "them", "there", "these", "this", "those", "through", "to",
                "was", "were", "with", "within"}
        cause_terms = {w for w in re.findall(r"[a-z]{4,}", causal.group(1).casefold()) if w not in stop}
        proof_terms = set(re.findall(r"[a-z]{4,}", q))
        missing = sorted(cause_terms - proof_terms)
        if len(cause_terms) >= 2 and len(missing) >= 2:
            return "the causal explanation is not supported by the cited quote: " + ", ".join(missing[:4])

    if (_NEGATIVE_EVENT.search(proof) or _NEGATED_ACTION.search(proof)) and _POSITIVE_EVENT.search(claim) and not _CANCEL_WORD.search(claim):
        return "the quote negates or reverses the event, but the claim states a positive action"
    if _NEGATIVE_EVENT.search(claim) or _NEGATED_ACTION.search(claim):
        if _POSITIVE_EVENT.search(proof) and not (_NEGATIVE_EVENT.search(proof) or _NEGATED_ACTION.search(proof)):
            return "the claim negates or reverses an action that its quote states positively"

    if re.search(r"\b(?:approved|approves|completed|completed the acquisition|closed the deal|commenced operations)\b", c):
        if _PENDING.search(proof) and not _APPROVED.search(proof):
            return "the claim upgrades a proposal, recommendation or pending approval to an approved/completed action"
    if _COMPLETED.search(claim) and re.search(r"\b(?:subject to|awaiting|pending|will seek|seeks)\b.{0,45}\b(?:approval|clearance|consent)\b", proof, re.I):
        if not _COMPLETED.search(proof):
            return "the claim says the transaction is completed while its quote says an approval or condition is pending"

    if _RISE.search(claim) and _FALL.search(proof) and not _RISE.search(proof):
        return "the claim says the measure rose, but its quote describes a fall or reduction"
    if _FALL.search(claim) and _RISE.search(proof) and not _FALL.search(proof):
        return "the claim says the measure fell, but its quote describes a rise or increase"

    # Proper-name phrases in the claim must be in the quoted evidence, unless they are the listed issuer itself.
    issuer = {_norm(n) for n in issuer_names if str(n or "").strip()}
    issuer |= {re.sub(r"\b(?:limited|ltd|private|pvt)\b\.?$", "", x).strip() for x in list(issuer)}
    for match in re.finditer(r"\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,3}\b", claim):
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
    # Words like "achieved a record" describe a reported result; they do not
    # claim that prior guidance was met. Run the comparison only when the claim
    # explicitly refers to a target, guidance, outlook, forecast, or commitment.
    if not _RESULT_VERB.search(text) or not re.search(r"\b(?:guidance|targets?|outlook|forecast|goal|commitment)\b", text, re.I):
        return None
    memory_quotes = [str(e.get("quote") or "") for e in evidence if e.get("source") == "company_memory"]
    current_quotes = [str(e.get("quote") or "") for e in evidence if e.get("source") == "current_filing"]
    if not memory_quotes or not current_quotes:
        return "a claim that guidance was met or missed needs both prior guidance and current-period evidence"
    prior = " ".join(memory_quotes)
    current = " ".join(current_quotes)
    pmetrics = {m.casefold() for m in _METRIC.findall(prior)}
    cmetrics = {m.casefold() for m in _METRIC.findall(current)}
    if not pmetrics.intersection(cmetrics):
        return "the prior guidance and current result do not identify the same measure"
    prior_basis = "consolidated" if re.search(r"\bconsolidated\b", prior, re.I) else "standalone" if re.search(r"\bstandalone\b", prior, re.I) else None
    current_basis = "consolidated" if re.search(r"\bconsolidated\b", current, re.I) else "standalone" if re.search(r"\bstandalone\b", current, re.I) else None
    if not prior_basis or not current_basis or prior_basis != current_basis:
        return "the prior guidance and current result do not establish the same standalone/consolidated basis"
    if _NO_GUIDANCE.search(prior) or not _GUIDANCE.search(prior):
        return "the historical evidence does not establish a forward-looking target or guidance"
    target_fy = {x.upper().replace(" ", "") for x in re.findall(r"\bFY\s*\d{2,4}\b", prior, re.I)}
    actual_fy = {x.upper().replace(" ", "") for x in re.findall(r"\bFY\s*\d{2,4}\b", current, re.I)}
    target_quarters = {re.sub(r"\s+", "", x.upper()) for x in re.findall(r"\bQ[1-4]\s*FY\s*\d{2,4}\b", prior, re.I)}
    actual_quarters = {re.sub(r"\s+", "", x.upper()) for x in re.findall(r"\bQ[1-4]\s*FY\s*\d{2,4}\b", current, re.I)}
    if not (target_fy or target_quarters):
        return "the prior guidance quote does not specify a period that can be matched to the current result"
    if not (actual_fy or actual_quarters):
        return "the current result quote does not specify a period that can be matched to the guidance"
    if target_fy and not actual_fy:
        return "the current result does not identify the fiscal year needed to assess this target"
    if target_fy and actual_fy and not target_fy.intersection(actual_fy):
        return "the target and actual refer to different fiscal years"
    if target_quarters and not actual_quarters:
        return "the current result does not identify the quarter needed to assess this target"
    if target_quarters and actual_quarters and not target_quarters.intersection(actual_quarters):
        return "the target and actual refer to different quarters"
    if target_fy and actual_quarters and target_fy.intersection(actual_fy) and not target_quarters:
        if not re.search(r"\b(?:full[- ]year|year ended|annual results|for the year)\b", current, re.I):
            return "an annual target cannot be judged against a quarterly result before the target period ends"
    # Only compare a directly quoted percentage margin with one unambiguous target and actual.
    # Other measure types need their own deterministic comparator; do not guess.
    if not re.search(r"\b(?:ebitda|operating|gross|net interest|net)\s+margin\b", prior, re.I):
        return "the target comparison is not a supported deterministic margin comparison"
    pcts = [float(x.replace(",", "")) for x in _PERCENT.findall(prior)]
    ccts = [float(x.replace(",", "")) for x in _PERCENT.findall(current)]
    if len(pcts) != 1 or len(ccts) != 1:
        return "the target comparison lacks one unambiguous quoted percentage for both target and actual"
    target, actual = pcts[0], ccts[0]
    if re.search(r"\b(?:up to|at most|maximum|not more than|no more than)\b", prior, re.I):
        return "the target is an upper bound and needs a separate comparator"
    t = text.casefold()
    if ("missed" in t or "fell short" in t) and actual >= target:
        return "the claim says the margin target was missed, but the quoted actual is at or above the target"
    if ("met" in t or "achieved" in t) and actual < target:
        return "the claim says the margin target was met, but the quoted actual is below the target"
    if "beat" in t and actual <= target:
        return "the claim says the target was beaten, but the quoted actual does not exceed it"
    if "exceeded" in t and actual <= target:
        return "the claim says the target was exceeded, but the quoted actual does not exceed it"
    return None


def validate_narrative(items, doc: str, memory: str, number_check, current_url: str | None = None,
                       issuer_names=(), current_quote_check=None) -> list[dict]:
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
            found = (bool(current_quote_check(quote)) if source == "current_filing" and current_quote_check
                     else _contains(corpus, quote))
            if not found:
                errors.append("the quoted evidence is not found in its stated source")
                continue
            source_url = current_url if source == "current_filing" else None
            if source == "company_memory":
                # Only reuse a URL already present on the exact memory line containing the evidence.
                line = next((ln for ln in str(memory or "").splitlines() if _contains(ln, quote)), "")
                m = re.search(r"https?://[^\s)]+", line)
                source_url = m.group(0).rstrip(".,") if m else None
            evidence.append({"source": source, "quote": quote, "source_url": source_url})
        if not evidence:
            errors.append("no verifiable source quote")
        quotes = [e["quote"] for e in evidence]
        if evidence and not number_check(text, quotes):
            errors.append("a number in the narrative is not backed by its cited evidence")
        if evidence:
            why = semantic_reason(text, " ".join(quotes), issuer_names=issuer_names)
            if why:
                errors.append(why)
            compare_why = _guidance_comparison_reason(text, evidence)
            if compare_why:
                errors.append(compare_why)
        out.append({"text": text, "evidence": evidence, "shown": not errors,
                    "reason": "; ".join(dict.fromkeys(errors)) or None})
    return out
