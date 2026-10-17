"""What management said on the last earnings call, set beside what this quarter's results show (owner, 18 Oct 2026).

Facts come from scripts/management_said.py: management's own words, each with its exact quote, found in the transcript by code. This
module chooses the forward-looking ones and pairs each with the results figure it is about, when the card has that figure. It judges
nothing ("beat", "missed"): the words and the figure stand side by side, each with its source."""
from __future__ import annotations

import re

FORWARD = re.compile(r'\b(?:expect\w*|target\w*|aim\w*|strive\w*|exit\w*|guid\w*|outlook|will|confident|turnaround|optimistic|improv\w*|'
                     r'plan\w*|intend\w*|on track|going forward|anticipat\w*|should|commit\w*)\b', re.IGNORECASE)
NO_GUIDANCE = re.compile(r"(?:do not|don't|doesn't|does not)\s+(?:provide|give)\b.*guidance", re.IGNORECASE)
TOPICS = ('guidance', 'margins', 'demand', 'deals', 'people', 'pricing')

# what a statement is about -> the label of the results figure that answers it (checked against the card's own metric labels)
MEASURES = (
    (re.compile(r'operating margin', re.I), re.compile(r'operating\s+margin|ebit\s*margin', re.I)),
    (re.compile(r'ebitda margin', re.I), re.compile(r'ebitda\s+margin', re.I)),
    (re.compile(r'attrition', re.I), re.compile(r'attrition', re.I)),
    (re.compile(r'workforce|headcount|employee base|employees', re.I), re.compile(r'workforce|headcount|employees', re.I)),
    (re.compile(r'\bmargins?\b', re.I), re.compile(r'operating\s+margin|ebit\s*margin|ebitda\s+margin', re.I)),
)


def forward_facts(facts: list[dict]) -> list[dict]:
    """The statements that look ahead (expect, target, exit at, will turn around), in the order given; a statement that there is no
    guidance is kept, as it is itself the position."""
    out = []
    for f in facts or []:
        text = f'{f.get("statement") or ""} {f.get("quote") or ""}'
        if f.get('topic') in TOPICS and (FORWARD.search(text) or NO_GUIDANCE.search(text)):
            out.append(f)
    return out


def measure_for(fact: dict):
    """The regex of the results figure this statement is about, or None."""
    text = f'{fact.get("statement") or ""} {fact.get("quote") or ""}'
    for said_rx, label_rx in MEASURES:
        if said_rx.search(text):
            return label_rx
    if fact.get('topic') == 'margins':     # "we want to exit at 25% plus" under margins: the margin the results report
        return MEASURES[-1][1]
    return None


def pick(said_doc: dict | None, as_of, limit: int = 3, metrics: list[dict] | None = None) -> list[dict]:
    """Up to `limit` items for a results card: [{'statement', 'quote', 'speaker', 'call_date', 'source_url', 'metric': the card's metric
    dict it is paired with or None}]. Only the latest call before `as_of`; statements with a paired figure first, then the other
    forward-looking ones, and no more than one that has nothing to pair with beyond the position on guidance."""
    calls = [c for c in (said_doc or {}).get('calls') or [] if str(c.get('call_date') or c.get('filed') or '') < str(as_of)[:10]]
    if not calls:
        return []
    call = sorted(calls, key=lambda c: str(c.get('call_date') or c.get('filed')))[-1]
    paired, loose = [], []
    for f in forward_facts(call.get('facts') or []):
        rx = measure_for(f)
        metric = next((m for m in (metrics or []) if rx and rx.search(str(m.get('label') or ''))), None) if rx else None
        item = {'statement': f.get('statement'), 'quote': f.get('quote'), 'speaker': f.get('speaker'),
                'call_date': call.get('call_date') or call.get('filed'), 'source_url': call.get('source_url'), 'metric': metric}
        (paired if metric else loose).append(item)
    rank = {t: i for i, t in enumerate(('guidance', 'demand', 'margins', 'deals', 'pricing', 'people'))}
    loose_sorted = sorted(loose, key=lambda i: rank.get(next((f.get('topic') for f in call.get('facts') or [] if f.get('statement') == i['statement']), ''), 9))
    return (paired + loose_sorted)[:limit]
