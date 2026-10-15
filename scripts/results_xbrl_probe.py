"""Which NSE endpoint lists quarterly financial results with their XBRL, and what is in that XBRL (read-only probe).

The endpoints below are candidates to confirm, not known contracts: for each, the HTTP answer, its shape, every
field with how often it is filled, the fields that look like links, and two sample rows. Then, for up to two
XBRL links found, the file's size, root, contexts and its first facts (name, context, unit, value).
Prints only: no R2, no model. Markdown to stdout and $GITHUB_STEP_SUMMARY.
"""
from __future__ import annotations

import json
import os
import re
import sys
import xml.etree.ElementTree as ET
from collections import Counter
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from collectors.nse_events.client import BASE, NSEClient  # noqa: E402

out: list[str] = []


def short(v, n=700):
    s = v if isinstance(v, str) else json.dumps(v, default=str, ensure_ascii=False)
    return s if len(s) <= n else s[:n] + '...'


def rows_of(data):
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for k, v in data.items():
            if isinstance(v, list) and v and isinstance(v[0], dict):
                return v
    return []


def probe(nse: NSEClient, url: str) -> list[dict]:
    out.append(f'#### `{url}`')
    try:
        data = nse.get(url, timeout=30, retries=2)
    except Exception as exc:  # noqa: BLE001 -- a candidate that fails is a finding
        out.extend([f'Failed: {type(exc).__name__}: {short(str(exc), 300)}', ''])
        return []
    rows = rows_of(data)
    top = list(data)[:15] if isinstance(data, dict) else f'list of {len(data)}'
    out.append(f'Top level {short(top, 300)}; {len(rows)} rows.')
    if not rows:
        out.extend([f'Body: `{short(data, 500)}`', ''])
        return []
    filled = Counter(k for r in rows for k, v in r.items() if v not in (None, '', '-'))
    out.append('Fields: ' + ', '.join(f'`{k}` {filled[k]}' for k in sorted({k for r in rows for k in r})))
    links = sorted({k for r in rows for k, v in r.items() if isinstance(v, str) and v.startswith('http')})
    for k in links:
        out.append(f'- link field `{k}`: e.g. {short([r.get(k) for r in rows[:3]], 400)}')
    for r in rows[:2]:
        out.append(f'Sample: `{short(r)}`')
    out.append('')
    return rows


def xbrl_links(rows: list[dict]) -> list[str]:
    found = []
    for r in rows:
        for v in r.values():
            if isinstance(v, str) and v.startswith('http') and re.search(r'xbrl|\.xml$', v, re.I) and v not in found:
                found.append(v)
    return found


def describe_xbrl(nse: NSEClient, url: str):
    out.append(f'#### XBRL file `{url}`')
    try:
        text = nse.get(url, as_json=False, timeout=30, retries=2)
    except Exception as exc:  # noqa: BLE001
        out.extend([f'Failed: {type(exc).__name__}: {short(str(exc), 300)}', ''])
        return
    out.append(f'{len(text)} characters; starts `{short(text[:160], 160)}`')
    try:
        root = ET.fromstring(re.sub(r'^\s*<\?xml[^>]*\?>', '', text))
    except ET.ParseError as exc:
        out.extend([f'Not XML: {exc}', ''])
        return
    contexts = [el for el in root if el.tag.endswith('}context')]
    facts = [el for el in root if el.get('contextRef')]
    out.append(f'Root `{root.tag}`; {len(contexts)} contexts; {len(facts)} facts.')
    for c in contexts[:4]:
        out.append(f'- context `{c.get("id")}`: {short(" ".join(t.strip() for t in c.itertext() if t.strip()), 200)}')
    names = Counter(el.tag.split('}')[-1] for el in facts)
    out.append(f'{len(names)} distinct fact names; contexts used: {dict(Counter(el.get("contextRef") for el in facts).most_common(8))}')
    for el in facts[:90]:
        out.append(f'- `{el.tag.split("}")[-1]}` [{el.get("contextRef")}] {el.get("unitRef") or ""} '
                   f'{el.get("decimals") or ""}: {short((el.text or "").strip(), 80)}')
    out.append('')


def main() -> int:
    nse = NSEClient()
    today = date.today()
    d = lambda x: x.strftime('%d-%m-%Y')  # noqa: E731
    a, b = d(today - timedelta(days=3)), d(today)
    integrated = (f'{BASE}/api/integrated-filing-results?index=equities&from_date={a}&to_date={b}'
                  '&type=Integrated%20Filing-%20Financials')
    candidates = [integrated, integrated + '&page=2', integrated + '&size=100']
    out.extend(['## NSE integrated-filing results: paging and XBRL', ''])
    links = []
    for url in candidates:
        rows = probe(nse, url)
        try:
            meta = nse.get(url, timeout=30, retries=1)
            out.append(f'Paging: { {k: meta.get(k) for k in ("size", "page", "totalCount")} } ; first seq_Id '
                       f'{rows[0].get("seq_Id") if rows else None}; last {rows[-1].get("seq_Id") if rows else None}')
            out.append(f'type_Sub: {dict(Counter(r.get("type_Sub") for r in rows))}; consolidated: '
                       f'{dict(Counter(r.get("consolidated") for r in rows))}; qe_Date: {dict(Counter(r.get("qe_Date") for r in rows))}')
            out.append('')
        except Exception as exc:  # noqa: BLE001
            out.append(f'Paging not read: {type(exc).__name__}')
        for link in xbrl_links(rows):
            if link not in links:
                links.append(link)
    kinds = {}
    for link in links:   # one file of each kind: INDAS, NBFC_INDAS, BANKING ...
        kind = re.sub(r'_\d+_\d+_WEB\.xml$', '', link.rsplit('/', 1)[-1])
        kinds.setdefault(kind, link)
    out.append(f'XBRL kinds: {list(kinds)}')
    for link in list(kinds.values())[:3]:
        describe_xbrl(nse, link)
    text = '\n'.join(out) + '\n'
    print(text)
    if os.environ.get('GITHUB_STEP_SUMMARY'):
        with open(os.environ['GITHUB_STEP_SUMMARY'], 'a', encoding='utf-8') as f:
            f.write(text)
    return 0


if __name__ == '__main__':
    sys.exit(main())
