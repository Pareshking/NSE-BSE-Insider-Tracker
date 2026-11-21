"""Mutual fund month-end portfolios: what each fund house held, stock by stock, and what changed in the month.

Source: every fund house publishes its schemes' portfolios as on the last day of each month, by the 10th of the next
(SEBI Master Circular for Mutual Funds; AMFI's Portfolio Disclosure page links each house's page). The file is a
workbook, one sheet per scheme, with a header row holding "ISIN" and "Quantity" (the SEBI format), sometimes zipped,
sometimes the old .xls format. This module reads any of them the same way and never guesses a column:

    parse_workbook(body, filename) -> one row per holding line: sheet, scheme, isin, name, quantity, value_lakh,
                                      pct_aum (as filed: a fraction or a percent, see `pct_scale`)

NPS pension fund managers file the PFRDA form the same way (a sheet per scheme: Particulars, ISIN No., Industry,
Quantity or No of Units, Market Value, % of Portfolio), with the value in rupees, not lakh: the house says which
(`value_unit`), and `value_lakh` is always lakh.

A sheet without such a header row is skipped and counted (index sheets, notes). Only equity shares are kept for the
stock tables (`is_equity`: an INE ISIN whose security code is 01, the depositories' code for equity shares); every
other line is counted, not dropped silently, and kept: `parse_workbook_lines` gives every filled row of every sheet
read, with its kind (equity, debt, money market, cash, derivative, other), and every sheet skipped with its reason
(archive/mf_lines/ and archive/mf_sheets_skipped/, scripts/mf_portfolios.py).

    holdings(rows, amc, month)       -> one row per fund house, month and ISIN: shares, value, schemes
    changes(cur, prev, factors)      -> shares added or cut in the month per fund house and ISIN, a split or bonus
                                        between the two month-ends applied to the earlier count first
    by_stock(changes)                -> per ISIN: fund houses adding, cutting, starting, exiting, net shares

Coverage is never claimed: `coverage()` compares the shares the collected houses hold with the mutual-fund holding the
company itself filed in its shareholding pattern (a quarter end), so the page can say how much of the industry the
month's figures cover.
"""
from __future__ import annotations

import io
import json
import re
import zipfile

import pandas as pd

ISIN = re.compile(r'^IN[A-Z0-9]{9}[0-9]$')
# Index funds, ETFs and funds of funds buy by rule, not by choice (a new total-market index fund buys 500 stocks in
# its first month): their shares are kept apart so "funds adding" means a fund manager's decision.
PASSIVE = re.compile(r'\betf\b|exchange traded|index fund|\bindex\b|\bnifty\b|\bsensex\b|\bbse \d|\bbse (?:total|sensex|midcap|smallcap|'
                     r'bharat|india|psu|healthcare|it|power|capital|select)|fund of funds?|\bfof\b|arbitrage', re.I)
HEADER_SCAN = 40      # rows from the top of a sheet searched for the header row
BLOCK = re.compile(r'^scheme\s*:\s*', re.I)   # 'SCHEME: UTI - Large Cap Fund', a scheme's title row
SCHEME_SCAN = 12      # rows from the top searched for the scheme name
VALUE_UNIT = {'lakh': 1.0, 'rupee': 1e5}   # the filed market value / this = Rs lakh


def is_equity(isin: pd.Series) -> pd.Series:
    s = isin.astype(str)
    return s.str.startswith('INE') & s.str[7:9].eq('01')


def _norm(v) -> str:
    return re.sub(r'\s+', ' ', str(v)).strip().lower() if v is not None and not (isinstance(v, float) and pd.isna(v)) else ''


def _scheme(rows: list) -> str | None:
    """The scheme's name from the top of the sheet: the cell after 'Scheme name', or the first long cell naming a fund."""
    first = None
    for r in rows[:SCHEME_SCAN]:
        cells = [c for c in r if _norm(c)]
        for i, c in enumerate(cells):
            t = _norm(c)
            if 'scheme name' in t or re.match(r'name of (?:the )?scheme', t):   # 'Name Of Scheme :' (NPS, SBI)
                rest = cells[i + 1:]
                if rest:
                    return str(rest[0]).strip()
                tail = str(c).split(':', 1)[-1].strip()
                if tail and _norm(tail) != t:
                    return tail
            if first is None and ('fund' in t or 'plan' in t or 'etf' in t) and 10 < len(t) < 200 and t not in (
                    'mutual fund',) and not t.strip('() .').endswith(' mutual fund') and 'portfolio' not in t \
                    and 'investment manager' not in t:
                first = str(c).strip()
    return first


def _is_qty(x: str) -> bool:
    """A quantity column: 'Quantity', 'Qty', 'No. of shares', or 'No of Units' (ICICI Pension Fund's Tier II sheets)."""
    return 'quantity' in x or x == 'qty' or bool(re.match(r'no\.? ?of (?:shares|units)$', x))


def _header(rows: list) -> tuple[int, dict] | None:
    for k, r in enumerate(rows[:HEADER_SCAN]):
        n = [_norm(c) for c in r]
        if not any(x.startswith('isin') for x in n) or not any(_is_qty(x) for x in n):
            continue
        col: dict = {}
        for j, x in enumerate(n):
            if x.startswith('isin') and 'isin' not in col:
                col['isin'] = j
            elif _is_qty(x) and 'qty' not in col:
                col['qty'] = j
            elif ('market' in x or 'fair value' in x or x.replace('_', ' ').startswith(('value', 'mkt'))) and 'val' not in col:
                col['val'] = j   # 'Mkt_Value' (NPS, SBI Pension Funds), 'Mkt Value Rs. in Lacs' (Sundaram)
            elif ('% to' in x or '% of' in x or 'to net assets' in x or x in ('%', '% aum')) and 'pct' not in col:
                col['pct'] = j
            elif ('name of' in x or 'instrument' in x or 'issuer' in x or x in ('company', 'security', 'particulars')) \
                    and 'name' not in col:   # 'Particulars': the PFRDA form's name column
                col['name'] = j
        return k, col
    return None


def parse_rows(sheet: str, rows: list) -> tuple[list[dict], str | None]:
    """Holding lines of one sheet, and why the sheet was skipped (None when read)."""
    h = _header(rows)
    if h is None:
        return [], 'no ISIN and Quantity header'
    k, col = h
    scheme = BLOCK.sub('', _scheme(rows[:k + 1]) or sheet).strip() or sheet
    out = []
    for r in rows[k + 1:]:
        r = list(r)
        # One sheet holding every scheme, each block opened by a 'SCHEME: name' row (UTI): the block's name
        # applies to the lines under it.
        title = next((str(c) for c in r if isinstance(c, str) and BLOCK.match(c.strip())), None)
        if title is not None and BLOCK.sub('', title.strip()).strip():
            scheme = BLOCK.sub('', title.strip()).strip()
            continue
        if col['isin'] >= len(r):
            continue
        isin = str(r[col['isin']] or '').strip().upper()
        if not ISIN.match(isin):
            continue
        g = lambda key: r[col[key]] if key in col and col[key] < len(r) else None  # noqa: E731
        out.append({'sheet': sheet, 'scheme': scheme, 'isin': isin, 'name': (str(g('name')).strip() if g('name') is not None else None),
                    'quantity': pd.to_numeric(g('qty'), errors='coerce'), 'value_lakh': pd.to_numeric(g('val'), errors='coerce'),
                    'pct_aum': pd.to_numeric(g('pct'), errors='coerce')})
    return out, None


def _books(body: bytes, filename: str):
    """(inner name, bytes) for each workbook in the body: the body itself, or each workbook inside a zip."""
    if body[:2] == b'PK' and not re.search(r'\.xlsx?$', filename, re.I) or filename.lower().endswith('.zip'):
        with zipfile.ZipFile(io.BytesIO(body)) as z:
            inner = [n for n in z.namelist() if re.search(r'\.(xlsx|xlsm|xls)$', n, re.I) and not n.startswith('__MACOSX')]
            if inner:
                for n in inner:
                    yield n, z.read(n)
                return
            if '[Content_Types].xml' in z.namelist():   # an .xlsx itself (a zip by format)
                yield filename, body
                return
        return
    yield filename, body


def _sheets(name: str, data: bytes):
    """(sheet name, list of row tuples) for each sheet, whatever the format."""
    if data[:2] == b'PK':
        import openpyxl
        wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
        for s in wb.sheetnames:
            yield s, list(wb[s].iter_rows(values_only=True))
        return
    if data[:8] == b'\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1':   # the old .xls (OLE2) format
        frames = pd.read_excel(io.BytesIO(data), sheet_name=None, header=None, engine='xlrd')
        for s, df in frames.items():
            yield s, [tuple(None if pd.isna(c) else c for c in row) for row in df.itertuples(index=False)]
        return
    raise ValueError(f'{name}: not a workbook (first bytes {data[:8]!r})')


def parse_workbook(body: bytes, filename: str, value_unit: str = 'lakh') -> tuple[pd.DataFrame, dict]:
    """Every holding line in the file, and a count of what was read and skipped. `value_unit` is the unit the file's
    market value is in, as the filer states it: 'lakh' (the SEBI format, "Rs. in Lakhs") or 'rupee' (the PFRDA form
    NPS pension funds file, "Amount in Rs."); `value_lakh` is always in lakh."""
    df, report, _, _ = _parse(body, filename, value_unit, lines=False)
    return df, report


def _parse(body: bytes, filename: str, value_unit: str, lines: bool):
    """One pass over the file's sheets: `parse_workbook`'s rows and report and, with `lines`, every line of every sheet
    read (`line_rows`) and every sheet skipped (`parse_workbook_lines`)."""
    if value_unit not in VALUE_UNIT:
        raise ValueError(f'value_unit {value_unit!r}: one of {sorted(VALUE_UNIT)}')
    rows, report = [], {'workbooks': 0, 'sheets': 0, 'sheets_read': 0, 'skipped': {}, 'value_unit': value_unit}
    all_lines, skipped = [], []
    for name, data in _books(body, filename):
        report['workbooks'] += 1
        wb = '' if name == filename else name     # the file's name inside a zip; blank for a plain workbook
        for sheet, srows in _sheets(name, data):
            report['sheets'] += 1
            got, why = parse_rows(sheet, srows)
            if why:
                report['skipped'][why] = report['skipped'].get(why, 0) + 1
                if lines:
                    skipped.append({'workbook': wb, 'sheet': sheet, 'reason': why, 'rows': len(srows),
                                    'filled_rows': sum(1 for r in srows if _filled(r))})
                continue
            report['sheets_read'] += 1
            rows += got
            if lines:
                # A failure here must never cost the equity rows above: the sheet is listed as not read line by line.
                try:
                    all_lines += [dict(x, workbook=wb) for x in line_rows(sheet, srows, value_unit)[0]]
                except Exception as exc:  # noqa: BLE001
                    skipped.append({'workbook': wb, 'sheet': sheet, 'reason': f'lines not read ({type(exc).__name__}: {exc})'[:300],
                                    'rows': len(srows), 'filled_rows': sum(1 for r in srows if _filled(r))})
    df = pd.DataFrame(rows, columns=['sheet', 'scheme', 'isin', 'name', 'quantity', 'value_lakh', 'pct_aum'])
    df['value_lakh'] = pd.to_numeric(df['value_lakh'], errors='coerce') / VALUE_UNIT[value_unit]
    report['lines'] = int(len(df))
    report['equity_lines'] = int(is_equity(df['isin']).sum()) if len(df) else 0
    report['equity_lines_no_quantity'] = int((is_equity(df['isin']) & df['quantity'].isna()).sum()) if len(df) else 0
    return df, report, all_lines, skipped


# --- every line, not only equity (owner, 21 Nov 2026: nothing may exist only in raw) ------------------------------------
#
# `parse_workbook` above gives what it always gave (the equity tables read it). `parse_workbook_lines` reads, in the same
# pass and with the same header finder, EVERY filled row of every sheet read: the title rows above
# the header, the header, section headings, holdings with or without an ISIN (TREPS, net receivables, cash), totals and
# notes. Each line carries its kind as the workbook says it: the section heading above it ('EQUITY & EQUITY RELATED',
# 'Debt Instruments', 'Money Market Instruments', 'Derivatives', 'Others' ...), else for a line without such a heading
# an equity share by its ISIN code (`is_equity`), else its own name; nothing matched is 'other', never guessed.
# Sheets without the header are listed with their reason (`skipped`), and no row is made up from them.

LINE_KINDS = ('equity', 'debt', 'money market', 'cash', 'derivative', 'other')
# Words on a heading (or a line's own name) and the kind they name, tried in this order (so 'Equity Derivatives' is a
# derivative and 'Debt - Money Market' money market). 'other' here is a heading that names a kind outside the five
# ('Others', 'Units of REITs', 'Gold'), so the lines under it are not left in the section above.
KIND_WORDS = [
    ('derivative', re.compile(r'derivative|\bfutures?\b|\bswaps?\b|options? contracts?|index options?', re.I)),
    ('money market', re.compile(r'money market|commercial papers?|certificates? of deposit|treasury bills?|\bt-?bills?\b|'
                                r'\btreps\b|tri-?party repo|reverse repo|\bcblo\b', re.I)),
    ('cash', re.compile(r'\bcash\b|net receivables?|net payables?|net current assets?|margin money', re.I)),
    ('debt', re.compile(r'\bdebt\b|\bbonds?\b|debentures?|\bncds?\b|government securit|\bg-?secs?\b|\bgilts?\b|'
                        r'state development loans?|\bsdls?\b|sovereign|securiti[sz]ed|pass through|\bptcs?\b|zero coupon', re.I)),
    ('equity', re.compile(r'\bequit(?:y|ies)\b', re.I)),
    ('other', re.compile(r'^\W*others?\b|\breits?\b|\binvits?\b|mutual fund units|units of (?:mutual )?funds?|\bgold\b|'
                         r'\bsilver\b|alternative investment|\baifs?\b|fixed deposits?|term deposits?', re.I)),
]
TOTAL = re.compile(r'^\W*(?:sub[\s-]*total|grand total|total)\b', re.I)
# A heading under a section that does not change its kind: '(a) Listed / awaiting listing on Stock Exchanges', 'Unlisted'.
SUB_HEADING = re.compile(r'listed|awaiting listing|privately placed|non[\s-]*traded|thinly traded|\brated\b|unrated|'
                         r'^\W*nil\W*$|^\W*$', re.I)
HEADING_MAX = 120     # a text row longer than this is a note, not a heading (it changes no section)
LINE_COLS = ['workbook', 'sheet', 'row', 'row_type', 'scheme', 'isin', 'name', 'line_kind', 'kind_from', 'section',
             'quantity', 'value_lakh', 'pct_aum', 'rating', 'industry', 'in_equity_tables', 'cells']
SKIPPED_COLS = ['workbook', 'sheet', 'reason', 'rows', 'filled_rows']


def _words_kind(text: str) -> str | None:
    for kind, rx in KIND_WORDS:
        if rx.search(text or ''):
            return kind
    return None


def _cell_text(c):
    if c is None or (isinstance(c, float) and pd.isna(c)):
        return None
    if hasattr(c, 'isoformat'):
        return c.isoformat()
    return str(c)


def _filled(r) -> bool:
    return any(_norm(c) for c in r)


def _is_header_row(r) -> bool:
    n = [_norm(c) for c in r]
    return any(x.startswith('isin') for x in n) and any(_is_qty(x) for x in n)


def _extra_cols(header_row) -> dict:
    """Rating and industry columns of the header row (not used by the equity tables): 'Rating / Industry^' is both."""
    out: dict = {}
    for j, x in enumerate(_norm(c) for c in header_row):
        if 'rating' in x and 'rating' not in out:
            out['rating'] = j
        if 'industry' in x and 'industry' not in out:
            out['industry'] = j
    return out


def line_rows(sheet: str, rows: list, value_unit: str = 'lakh') -> tuple[list[dict], str | None]:
    """Every filled row of one sheet as a line, and why the sheet was skipped (then no lines). Uses the same header
    finder as `parse_rows`, so the 'holding' lines here are its lines exactly (same scheme, ISIN, quantity, value)."""
    h = _header(rows)
    if h is None:
        return [], 'no ISIN and Quantity header'
    k, col = h
    col = dict(col, **{key: j for key, j in _extra_cols(rows[k]).items()})
    scheme = BLOCK.sub('', _scheme(rows[:k + 1]) or sheet).strip() or sheet
    unit = VALUE_UNIT[value_unit]
    out = []
    section, section_kind = None, None

    def line(i, r, row_type, kind='other', kind_from='none', isin=None, **kw):
        cells = [_cell_text(c) for c in r]
        while cells and cells[-1] is None:
            cells.pop()
        g = lambda key: r[col[key]] if key in col and col[key] < len(r) else None  # noqa: E731
        name = g('name')
        val = pd.to_numeric(g('val'), errors='coerce')
        return {'sheet': sheet, 'row': i, 'row_type': row_type, 'scheme': scheme, 'isin': isin,
                'name': str(name).strip() if name is not None else None, 'line_kind': kind, 'kind_from': kind_from,
                'section': section, 'quantity': pd.to_numeric(g('qty'), errors='coerce'),
                'value_lakh': val / unit if pd.notna(val) else float('nan'), 'pct_aum': pd.to_numeric(g('pct'), errors='coerce'),
                'rating': _cell_text(g('rating')), 'industry': _cell_text(g('industry')),
                'cells': json.dumps(cells, ensure_ascii=False), **kw}

    for i, r in enumerate(rows, 1):
        r = list(r)
        if not _filled(r):
            continue
        if i <= k:
            out.append(line(i, r, 'title'))
            continue
        if i == k + 1 or _is_header_row(r):
            out.append(line(i, r, 'header'))
            continue
        title = next((str(c) for c in r if isinstance(c, str) and BLOCK.match(c.strip())), None)
        if title is not None and BLOCK.sub('', title.strip()).strip():
            scheme = BLOCK.sub('', title.strip()).strip()   # a new scheme's block: its own sections follow
            section, section_kind = None, None
            out.append(line(i, r, 'scheme_title'))
            continue
        isin = str(r[col['isin']] or '').strip().upper() if col['isin'] < len(r) else ''
        text = ' '.join(str(c).strip() for c in r if isinstance(c, str) and c.strip())
        g = lambda key: r[col[key]] if key in col and col[key] < len(r) else None  # noqa: E731
        numbers = any(pd.notna(pd.to_numeric(g(c), errors='coerce')) for c in ('qty', 'val', 'pct'))
        if ISIN.match(isin):
            # its own words: the name, then the industry / rating cell ('GOVERNMENT SECURITIES' on the PFRDA form)
            own = _words_kind(str(g('name') or '')) or _words_kind(str(g('industry') or '')) or _words_kind(str(g('rating') or ''))
            if section_kind is not None:
                kind, how = section_kind, 'heading'
            elif is_equity(pd.Series([isin])).iloc[0]:
                kind, how = 'equity', 'isin'
            elif own:
                kind, how = own, 'name'
            else:
                kind, how = 'other', 'none'
            out.append(line(i, r, 'holding', kind, how, isin))
            continue
        if numbers:   # a line with a value and no ISIN: TREPS, net receivables, cash, a total
            own = _words_kind(text) if not TOTAL.match(text) else None
            if own is not None:
                kind, how = own, 'name'
            elif section_kind is not None:
                kind, how = section_kind, 'heading'
            else:
                kind, how = 'other', 'none'
            out.append(line(i, r, 'total' if TOTAL.match(text) else 'value', kind, how, isin or None))
            continue
        # text only: a heading (it may open a section), a total's label, or a note
        if len(text) > HEADING_MAX or TOTAL.match(text):
            out.append(line(i, r, 'note' if len(text) > HEADING_MAX else 'total', section_kind or 'other',
                            'heading' if section_kind else 'none', isin or None))
            continue
        own = _words_kind(text)
        if own is not None:
            section, section_kind = text, own
        elif not SUB_HEADING.search(text):
            section, section_kind = text, 'other'   # a heading naming none of the kinds: what follows is not the above
        out.append(line(i, r, 'heading', section_kind or 'other', 'heading' if section_kind else 'none', isin or None))
    return out, None


def parse_workbook_lines(body: bytes, filename: str, value_unit: str = 'lakh'):
    """`parse_workbook`'s rows and report, unchanged, plus every line of every sheet read (`LINE_COLS`) and every sheet
    skipped with its reason (`SKIPPED_COLS`): (rows, report, lines, skipped). `workbook` is the file's name inside a zip,
    blank for a plain workbook."""
    df, report, lines, skipped = _parse(body, filename, value_unit, lines=True)
    ln = pd.DataFrame(lines, columns=LINE_COLS)
    ln['in_equity_tables'] = (ln['row_type'].eq('holding') & is_equity(ln['isin'].fillna('')) & ln['quantity'].notna()
                              ).astype(bool) if len(ln) else pd.Series(dtype=bool)
    for c in ('quantity', 'value_lakh', 'pct_aum'):
        ln[c] = pd.to_numeric(ln[c], errors='coerce').astype(float)
    ln['row'] = ln['row'].astype('int64')
    return df, report, ln, pd.DataFrame(skipped, columns=SKIPPED_COLS)


def holdings(rows: pd.DataFrame, amc: str, month: str) -> pd.DataFrame:
    """One row per ISIN for one fund house's month-end: shares held across its schemes, value, scheme count.
    Equity shares only; a line with no quantity is left out and counted by `parse_workbook`."""
    eq = rows[is_equity(rows['isin']) & rows['quantity'].notna()]
    if eq.empty:
        return pd.DataFrame(columns=['amc', 'month', 'isin', 'name', 'shares', 'active_shares', 'value_lakh', 'schemes',
                                     'active_schemes'])
    passive = eq['scheme'].astype(str).str.contains(PASSIVE)
    eq = eq.assign(_active=eq['quantity'].where(~passive, 0.0), _act_scheme=eq['scheme'].where(~passive))
    g = eq.groupby('isin', sort=False)
    out = g.agg(name=('name', 'first'), shares=('quantity', 'sum'), active_shares=('_active', 'sum'),
                value_lakh=('value_lakh', 'sum'), schemes=('scheme', 'nunique'), active_schemes=('_act_scheme', 'nunique')).reset_index()
    out.insert(0, 'month', month)
    out.insert(0, 'amc', amc)
    return out


def _key(name) -> str:
    n = re.sub(r'[^a-z0-9 ]', ' ', str(name or '').lower())
    n = re.sub(r'\b(limited|ltd|the|co|company|corporation|corp|india|inc)\b', ' ', n)
    return re.sub(r'\s+', ' ', n).strip()


def bridge_isins(cur: pd.DataFrame, prev: pd.DataFrame) -> dict:
    """{old ISIN: new ISIN} where one company's ISIN changed between the two month-ends (a merger into a renamed
    company, a split with a new ISIN): within one house an ISIN held before and not now, and an ISIN held now and not
    before, under the same company name. Only a one-to-one match counts; anything ambiguous is left as an exit and a
    new holding. (Oct 2026: JSW Dulux read as two houses starting it and two selling out.)"""
    out: dict = {}
    for amc in set(cur['amc']) & set(prev['amc']):
        c, p = cur[cur['amc'] == amc], prev[prev['amc'] == amc]
        gone = p[~p['isin'].isin(c['isin'])]
        new = c[~c['isin'].isin(p['isin'])]
        if gone.empty or new.empty:
            continue
        gk = gone.assign(_k=gone['name'].map(_key)).query('_k != ""')
        nk = new.assign(_k=new['name'].map(_key)).query('_k != ""')
        gk = gk[~gk['_k'].duplicated(keep=False)]
        nk = nk[~nk['_k'].duplicated(keep=False)]
        for k, old in zip(gk['_k'], gk['isin']):
            hit = nk.loc[nk['_k'] == k, 'isin']
            if len(hit) == 1 and out.get(old, hit.iloc[0]) == hit.iloc[0]:
                out[old] = hit.iloc[0]
    return out


def changes(cur: pd.DataFrame, prev: pd.DataFrame, factors: pd.DataFrame | None = None) -> pd.DataFrame:
    """Shares added or cut between two month-ends, per fund house and ISIN, for all schemes (`change`) and for active
    schemes only (`active_change`, what `kind` reads). `factors` (isin, factor): a split or bonus between the two dates
    multiplies the earlier counts (a 1:1 bonus is factor 2), so it is not read as buying. Only fund houses present in
    both months are compared (a house collected for one month only says nothing). `kind`: new, added, cut, exit, held,
    or passive (held only by index funds and ETFs in both months)."""
    both = set(cur['amc']) & set(prev['amc'])
    bridge = bridge_isins(cur, prev)
    if bridge:
        prev = prev.assign(isin=prev['isin'].replace(bridge))
        prev = prev.groupby(['amc', 'isin'], as_index=False).agg(name=('name', 'first'), shares=('shares', 'sum'),
                                                                 active_shares=('active_shares', 'sum'))
    c = cur[cur['amc'].isin(both)][['amc', 'month', 'isin', 'name', 'shares', 'active_shares', 'value_lakh']]
    p = prev[prev['amc'].isin(both)][['amc', 'isin', 'name', 'shares', 'active_shares']].rename(
        columns={'shares': 'shares_before', 'active_shares': 'active_before', 'name': '_name_before'})
    m = c.merge(p, on=['amc', 'isin'], how='outer')
    m['name'] = m['name'].fillna(m.pop('_name_before'))
    if factors is not None and len(factors):
        f = factors.drop_duplicates('isin').set_index('isin')['factor']
        m['factor'] = m['isin'].map(f).fillna(1.0)
    else:
        m['factor'] = 1.0
    m['month'] = m['month'].fillna(cur['month'].iloc[0] if len(cur) else None)
    for col in ('shares', 'active_shares', 'shares_before', 'active_before'):
        m[col] = m[col].fillna(0.0)
    m['shares_before'] = m['shares_before'] * m['factor']
    m['active_before'] = m['active_before'] * m['factor']
    m['change'] = m['shares'] - m['shares_before']
    m['active_change'] = m['active_shares'] - m['active_before']
    a, b = m['active_shares'], m['active_before']
    m['kind'] = 'held'
    m.loc[a.gt(0) & b.eq(0), 'kind'] = 'new'
    m.loc[a.eq(0) & b.gt(0), 'kind'] = 'exit'
    m.loc[a.gt(0) & b.gt(0) & m['active_change'].gt(0), 'kind'] = 'added'
    m.loc[a.gt(0) & b.gt(0) & m['active_change'].lt(0), 'kind'] = 'cut'
    m.loc[a.eq(0) & b.eq(0), 'kind'] = 'passive'
    m['isin_before'] = m['isin'].map({v: k for k, v in bridge.items()})
    return m


def by_stock(ch: pd.DataFrame) -> pd.DataFrame:
    """Per ISIN (active schemes): houses adding (incl. new), cutting (incl. exits), starting, exiting, net shares
    bought by active schemes, by all schemes, and active shares held at the two month-ends."""
    cols = ['isin', 'name', 'houses_adding', 'houses_cutting', 'houses_new', 'houses_exit', 'active_net', 'all_net',
            'active_shares', 'active_before', 'price', 'active_net_cr', 'houses_holding']
    if ch.empty:
        return pd.DataFrame(columns=cols)
    held = ch['shares'].gt(0)
    g = ch.assign(_add=ch['kind'].isin(['added', 'new']), _cut=ch['kind'].isin(['cut', 'exit']),
                  _new=ch['kind'].eq('new'), _exit=ch['kind'].eq('exit'), _hold=ch['active_shares'].gt(0),
                  _v=ch['value_lakh'].where(held), _s=ch['shares'].where(held)).groupby('isin', sort=False)
    out = g.agg(name=('name', 'first'), houses_adding=('_add', 'sum'), houses_cutting=('_cut', 'sum'),
                houses_new=('_new', 'sum'), houses_exit=('_exit', 'sum'), active_net=('active_change', 'sum'),
                all_net=('change', 'sum'), active_shares=('active_shares', 'sum'),
                active_before=('active_before', 'sum'), houses_holding=('_hold', 'sum'), _v=('_v', 'sum'), _s=('_s', 'sum')).reset_index()
    # The month-end price the houses valued it at (their filed market value over their shares); blank when no
    # collected house still holds it (an exit by all), never filled from elsewhere.
    out['price'] = (out['_v'] * 1e5 / out['_s']).where(out['_s'].gt(0))
    out['active_net_cr'] = out['active_net'] * out['price'] / 1e7
    return out[cols]


def tag_house_kind(ch: pd.DataFrame, h: pd.DataFrame) -> pd.DataFrame:
    """`house_kind` on each change row: 'mf' or 'pension', the house's `kind` in the holdings (a house archived before
    the column existed is a mutual fund). Named apart from `kind`, which on a change row is new / added / cut ..."""
    kinds = h.drop_duplicates('amc').set_index('amc')['kind'] if 'kind' in h else pd.Series(dtype=object)
    return ch.assign(house_kind=ch['amc'].map(kinds).fillna('mf'))


def stock_months(ch: pd.DataFrame) -> pd.DataFrame:
    """`by_stock` for every month and house kind: mutual funds and NPS pension funds counted apart, never mixed."""
    if 'house_kind' not in ch:
        ch = ch.assign(house_kind='mf')
    parts = [by_stock(g).assign(month=m, house_kind=k) for (m, k), g in ch.groupby(['month', 'house_kind'], sort=True)]
    return pd.concat(parts, ignore_index=True) if parts else by_stock(ch.iloc[:0]).assign(month=None, house_kind=None)


def month_end(month: str) -> pd.Timestamp:
    return (pd.Period(month, 'M').end_time).normalize()


def share_factors(actions: pd.DataFrame | None, prev_month: str, cur_month: str) -> pd.DataFrame:
    """(isin, factor) for bonuses and splits with an ex-date after the earlier month-end and on or before the later
    one: shares held before are multiplied by `factor` (a 1:1 bonus or a split of 10 into 5 doubles them). Built from
    the filed actions (`adjust.expected_factors`, a price factor: shares move by its inverse). A split that comes with
    a new ISIN shows as an exit from the old ISIN and a new holding of the new one; it is not bridged here."""
    from insiders_clean.adjust import expected_factors
    e = expected_factors(actions)
    if e.empty:
        return pd.DataFrame(columns=['isin', 'factor'])
    e = e[e['split_bonus'] & e['expected'].gt(0) & (e['ex_date'] > month_end(prev_month)) & (e['ex_date'] <= month_end(cur_month))]
    if e.empty:
        return pd.DataFrame(columns=['isin', 'factor'])
    return (1 / e.groupby('isin')['expected'].prod()).rename('factor').reset_index()


def company_shares(shareholding: pd.DataFrame | None, actions: pd.DataFrame | None, months: list[str]) -> pd.DataFrame:
    """(month, isin, total_shares, total_shares_quarter, total_shares_factor): the company's shares in issue on the
    same basis as the houses' month-end counts. The latest shareholding filing at or before the month-end gives the
    count; a bonus or split with an ex-date after that quarter end and on or before the month-end multiplies it, as
    `share_factors` multiplies the houses' earlier counts. Without it a split read wrong (Nov 2026, JSW Dulux: Rs 10
    shares split into Re 1 on 22 Oct 2026, the Sep quarter's 45.5m shares against the houses' post-split counts) shows
    "+3.16% of the company bought" where 0.316% was bought. A company with no filing at or before the month-end has no
    row: no share is stated, rather than one from a later count."""
    cols = ['month', 'isin', 'total_shares', 'total_shares_quarter', 'total_shares_factor']
    if shareholding is None or shareholding.empty or not {'isin', 'quarter_end', 'total_shares'} <= set(shareholding.columns):
        return pd.DataFrame(columns=cols)
    from insiders_clean.adjust import expected_factors
    sh = shareholding.assign(_q=pd.to_datetime(shareholding['quarter_end'], errors='coerce').dt.normalize(),
                             _t=pd.to_numeric(shareholding['total_shares'], errors='coerce'))
    sh = sh.dropna(subset=['isin', '_q', '_t'])
    sh = sh[sh['_t'].gt(0)].sort_values('_q').drop_duplicates(['isin', '_q'], keep='last')[['isin', '_q', '_t']]
    e = expected_factors(actions)
    e = e[e['split_bonus'] & e['expected'].gt(0)] if len(e) else e
    out = []
    for mth in months:
        end = month_end(mth)
        last = sh[sh['_q'] <= end].drop_duplicates('isin', keep='last')
        if last.empty:
            continue
        f = pd.Series(1.0, index=last.index)
        if len(e):
            x = last.merge(e, on='isin', how='inner')
            x = x[(x['ex_date'] > x['_q']) & (x['ex_date'] <= end)]
            if len(x):
                fx = (1 / x.groupby('isin')['expected'].prod())
                f = last['isin'].map(fx).fillna(1.0)
        out.append(pd.DataFrame({'month': mth, 'isin': last['isin'].to_numpy(), 'total_shares': (last['_t'] * f).to_numpy(),
                                 'total_shares_quarter': last['_q'].dt.strftime('%Y-%m-%d').to_numpy(),
                                 'total_shares_factor': f.to_numpy()}))
    return pd.concat(out, ignore_index=True)[cols] if out else pd.DataFrame(columns=cols)


def coverage(month_holdings: pd.DataFrame, filed: pd.DataFrame) -> dict:
    """Shares held by the collected houses against the mutual-fund shares each company filed (`filed`: isin,
    mf_shares, for a quarter end the same as the month). Median and share-weighted ratio over companies in both."""
    h = month_holdings.groupby('isin')['shares'].sum()
    f = filed.dropna(subset=['mf_shares']).set_index('isin')['mf_shares']
    both = h.index.intersection(f[f > 0].index)
    if not len(both):
        return {'companies': 0}
    r = (h[both] / f[both]).clip(upper=5)
    return {'companies': int(len(both)), 'median_ratio': float(r.median()), 'weighted_ratio': float(h[both].sum() / f[both].sum())}


# ---- Scheme by scheme -------------------------------------------------------------------------------------------
# Owner, 19 Nov 2026: "Each fund house has multiple equity schemes; are we covering buying and selling of all schemes
# or only a few?" A house's figures above net its schemes against each other (one scheme's buying hides another's
# selling). The same lines, kept per scheme, say which scheme moved; the scheme count check says how many of the
# house's schemes were read.

# Words that name a plan or an option of a scheme, not the scheme: a portfolio is filed per scheme, AMFI's NAV list per
# plan and option, and the same scheme is spelt differently from month to month and file to file.
_PLAN_WORDS = re.compile(
    r'\b(?:direct|regular|retail|institutional|plan|plans|option|options|growth|idcw|dividend (?:option|payout|pay out|reinvestment|re investment|plan|sweep)|payout|pay out|'
    r're ?investment|reinvest|bonus|daily|weekly|fortnightly|monthly|quarterly|half yearly|annual|yearly|'
    r'income distribution cum capital withdrawal|income distribution|capital withdrawal|segregated portfolio(?: \d+)?|'
    r'fund|funds|scheme|the|of|an|a|mf|mutual)\b')
_DESCRIPTION = re.compile(r'\(?\s*\ban?\s+open[ -]?ended\b.*$|\(?\s*\ba\s+close[ -]?ended\b.*$')   # 'X Fund (An open ended ...'
_FORMERLY = re.compile(r'\((?:\s*(?:formerly|erstwhile|earlier)[^)]*)\)|\b(?:formerly|erstwhile)(?: known as)?\b.*$')
_AS_ON = re.compile(r'\b(?:portfolio|statement|monthly|half yearly)?\s*(?:as (?:on|at)|for the month)\b.*$')


def _brand(house_name: str | None) -> str:
    """'SBI Mutual Fund' -> 'sbi', 'quant Mutual Fund' -> 'quant', 'Aditya Birla Sun Life Pension Fund' -> 'aditya birla
    sun life': the words every scheme name of the house starts with."""
    b = re.sub(r'[^a-z0-9 ]', ' ', str(house_name or '').lower().replace('&', ' and '))
    b = re.sub(r'\b(?:mutual fund|pension funds?|pension fund managers?|mf)\b', ' ', b)
    return re.sub(r'\s+', ' ', b).strip()


def scheme_key(name, house_name: str | None = None) -> str:
    """The same scheme across months and sources: lower case, the house's name in front taken off, plan and option words
    (Direct, Regular, Growth, IDCW ...), 'fund', descriptions ('An open ended ...') and former names taken off.
    'SBI Large Cap Fund - Direct Plan - Growth' and 'SBI LARGE CAP FUND (An open-ended equity scheme ...)' -> 'largecap'.
    Index funds and ETFs keep the words that make them passive (`PASSIVE` still reads them)."""
    t = str(name or '').lower().replace('&', ' and ').replace('–', '-').replace('’', "'")
    t = _FORMERLY.sub(' ', t)
    t = _DESCRIPTION.sub(' ', t)
    t = _AS_ON.sub(' ', t)
    t = re.sub(r'\(\s*\d+(?:\.\d+)?\s*%\s*\)|\boption\s*[a-z]\b|\bplan\s*[a-z]\b', ' ', t)   # Tata Value Fund 'Option A(5%)'
    t = re.sub(r'\bhealth care\b', 'healthcare', t)
    t = re.sub(r"[^a-z0-9 ]", ' ', t.replace("'", ''))
    t = re.sub(r'\s+', ' ', t).strip()
    brand = _brand(house_name)
    if brand and (t == brand or t.startswith(brand + ' ')):
        t = t[len(brand):]
    t = _PLAN_WORDS.sub(' ', t)
    t = re.sub(r'\b(large|mid|small|micro|multi|flexi)\s?cap\b', r'\1cap', t)   # 'Multicap' and 'Multi Cap' alike
    t = re.sub(r'\s+', ' ', t).strip()
    return t or re.sub(r'\s+', ' ', str(name or '').lower()).strip()


SCHEME_COLS = ['amc', 'month', 'scheme_key', 'scheme', 'isin', 'name', 'shares', 'value_lakh', 'passive']


def scheme_holdings(rows: pd.DataFrame, amc: str, month: str, house_name: str | None = None) -> pd.DataFrame:
    """One row per scheme and ISIN for one house's month-end, equity shares only (a line with no quantity left out, as in
    `holdings`): the scheme as filed and its key (`scheme_key`), shares, value, and whether the scheme is passive (index
    fund, ETF, fund of funds: `PASSIVE`). Summed over the schemes these rows are `holdings` exactly."""
    eq = rows[is_equity(rows['isin']) & rows['quantity'].notna()] if len(rows) else rows
    if eq is None or eq.empty:
        return pd.DataFrame(columns=SCHEME_COLS)
    eq = eq.assign(scheme_key=eq['scheme'].map(lambda s: scheme_key(s, house_name)),
                   _p=eq['scheme'].astype(str).str.contains(PASSIVE))
    out = eq.groupby(['scheme_key', 'isin'], sort=False).agg(
        scheme=('scheme', 'first'), name=('name', 'first'), shares=('quantity', 'sum'), value_lakh=('value_lakh', 'sum'),
        passive=('_p', 'max')).reset_index()
    out.insert(0, 'month', month)
    out.insert(0, 'amc', amc)
    return out[SCHEME_COLS]


def scheme_list(rows: pd.DataFrame, amc: str, month: str, house_name: str | None = None) -> pd.DataFrame:
    """Every scheme read in a house's month-end file(s), equity or not: key, name as filed, holding lines, equity lines,
    passive. The scheme count check (`scheme_coverage`) reads it; schemes holding no equity (debt, liquid) are in it
    too, so 'schemes read' is every scheme the file has."""
    cols = ['amc', 'month', 'scheme_key', 'scheme', 'lines', 'equity_lines', 'passive']
    if rows is None or rows.empty:
        return pd.DataFrame(columns=cols)
    r = rows.assign(scheme_key=rows['scheme'].map(lambda s: scheme_key(s, house_name)),
                    _eq=is_equity(rows['isin']) & rows['quantity'].notna(),
                    _p=rows['scheme'].astype(str).str.contains(PASSIVE))
    out = r.groupby('scheme_key', sort=False).agg(scheme=('scheme', 'first'), lines=('isin', 'size'),
                                                  equity_lines=('_eq', 'sum'), passive=('_p', 'max')).reset_index()
    out.insert(0, 'month', month)
    out.insert(0, 'amc', amc)
    out['equity_lines'] = out['equity_lines'].astype(int)
    return out[cols]


def house_from_schemes(sc: pd.DataFrame) -> pd.DataFrame:
    """`holdings`-shaped rows (amc, month, isin, name, shares, active_shares) from scheme rows: the check that the scheme
    table adds up to the house table, and the input `bridge_isins` takes."""
    if sc is None or sc.empty:
        return pd.DataFrame(columns=['amc', 'month', 'isin', 'name', 'shares', 'active_shares'])
    x = sc.assign(_a=sc['shares'].where(~sc['passive'].astype(bool), 0.0))
    return x.groupby(['amc', 'month', 'isin'], sort=False).agg(name=('name', 'first'), shares=('shares', 'sum'),
                                                               active_shares=('_a', 'sum')).reset_index()


SCHEME_CHANGE_COLS = ['amc', 'month', 'scheme_key', 'scheme', 'isin', 'isin_before', 'name', 'passive', 'scheme_seen',
                      'factor', 'shares_start', 'shares_end', 'change', 'value_lakh', 'status']


def scheme_changes(cur: pd.DataFrame, prev: pd.DataFrame, factors: pd.DataFrame | None = None) -> pd.DataFrame:
    """Per house, scheme and ISIN between two month-ends: shares at the start (a split or bonus in between applied, as in
    `changes`) and at the end, the change, the value at the end (Rs lakh, as filed), and `status`: new, added, cut, exit
    or held. An ISIN change is bridged per house exactly as `changes` bridges it (the same `bridge_isins` on the house's
    totals), so the scheme rows add up to the house rows. Only houses in both months are compared.

    `scheme_seen`: 'both' (the scheme is in the house's files at both month-ends), 'end_only' (not in the earlier file:
    a new scheme, or one whose name changed beyond what `scheme_key` matches) or 'start_only' (gone: merged, closed or
    renamed). A scheme seen at one end only has every line new or sold out; the page keeps such schemes apart."""
    if cur is None or prev is None or cur.empty or prev.empty:
        return pd.DataFrame(columns=SCHEME_CHANGE_COLS)
    both = set(cur['amc']) & set(prev['amc'])
    cur, prev = cur[cur['amc'].isin(both)], prev[prev['amc'].isin(both)]
    if cur.empty:
        return pd.DataFrame(columns=SCHEME_CHANGE_COLS)
    bridge = bridge_isins(house_from_schemes(cur), house_from_schemes(prev))
    if bridge:
        prev = prev.assign(isin=prev['isin'].replace(bridge))
        prev = prev.groupby(['amc', 'scheme_key', 'isin'], as_index=False, sort=False).agg(
            scheme=('scheme', 'first'), name=('name', 'first'), shares=('shares', 'sum'), passive=('passive', 'max'))
    c = cur[['amc', 'month', 'scheme_key', 'scheme', 'isin', 'name', 'shares', 'value_lakh', 'passive']].rename(
        columns={'shares': 'shares_end'})
    p = prev[['amc', 'scheme_key', 'isin', 'scheme', 'name', 'shares', 'passive']].rename(
        columns={'shares': 'shares_start', 'scheme': '_scheme0', 'name': '_name0', 'passive': '_passive0'})
    m = c.merge(p, on=['amc', 'scheme_key', 'isin'], how='outer')
    m['scheme'] = m['scheme'].fillna(m.pop('_scheme0'))
    m['name'] = m['name'].fillna(m.pop('_name0'))
    p0 = m.pop('_passive0')
    m['passive'] = [bool(v) if pd.notna(v) else False for v in m['passive'].combine_first(p0)]
    m['month'] = cur['month'].iloc[0]
    keys_c = set(zip(cur['amc'], cur['scheme_key']))
    keys_p = set(zip(prev['amc'], prev['scheme_key']))
    k = list(zip(m['amc'], m['scheme_key']))
    m['scheme_seen'] = ['both' if x in keys_c and x in keys_p else 'end_only' if x in keys_c else 'start_only' for x in k]
    f = factors.drop_duplicates('isin').set_index('isin')['factor'] if factors is not None and len(factors) else pd.Series(dtype=float)
    m['factor'] = m['isin'].map(f).fillna(1.0)
    m['shares_end'] = m['shares_end'].fillna(0.0)
    m['shares_start'] = m['shares_start'].fillna(0.0) * m['factor']
    m['change'] = m['shares_end'] - m['shares_start']
    s, e = m['shares_start'], m['shares_end']
    m['status'] = 'held'
    m.loc[s.eq(0) & e.gt(0), 'status'] = 'new'
    m.loc[s.gt(0) & e.eq(0), 'status'] = 'exit'
    m.loc[s.gt(0) & e.gt(0) & m['change'].gt(0), 'status'] = 'added'
    m.loc[s.gt(0) & e.gt(0) & m['change'].lt(0), 'status'] = 'cut'
    m['isin_before'] = m['isin'].map({v: k for k, v in bridge.items()})
    return m[SCHEME_CHANGE_COLS]


def month_prices(stock: pd.DataFrame | None) -> pd.DataFrame:
    """(month, house_kind, isin) -> price: the houses' filed value over their shares that month-end (`by_stock`), and the
    month-end before's where no collected house holds it any more (an exit by all), never a price from elsewhere."""
    if stock is None or stock.empty or 'price' not in stock:
        return pd.DataFrame(columns=['month', 'house_kind', 'isin', 'price'])
    s = stock if 'house_kind' in stock else stock.assign(house_kind='mf')
    p = s[['month', 'house_kind', 'isin', 'price']].drop_duplicates(['month', 'house_kind', 'isin'])
    p = p.sort_values(['house_kind', 'isin', 'month'])
    return p.assign(price=p['price'].fillna(p.groupby(['house_kind', 'isin'])['price'].shift(1)))


def value_scheme_changes(sc: pd.DataFrame, stock: pd.DataFrame | None) -> pd.DataFrame:
    """`change_cr` on each scheme change row: the change at the month's price (`month_prices`), the same price the house
    and stock figures use, so a house's schemes add up to the house's rupees. Blank where no price was filed."""
    if sc is None or sc.empty:
        return (sc if sc is not None else pd.DataFrame()).assign(change_cr=pd.Series(dtype=float))
    x = sc if 'house_kind' in sc else sc.assign(house_kind='mf')
    x = x.merge(month_prices(stock), on=['month', 'house_kind', 'isin'], how='left')
    return x.assign(change_cr=x['change'] * x.pop('price') / 1e7)


def scheme_month(sc: pd.DataFrame) -> pd.DataFrame:
    """Per month, house and scheme (from valued `scheme_changes`): net rupees (crore), bought and sold rupees, stocks
    added (new ones too), cut (exits too), new, sold out, held at the end. Small: what the site reads to rank schemes."""
    cols = ['month', 'amc', 'house_kind', 'scheme_key', 'scheme', 'passive', 'scheme_seen', 'net_cr', 'bought_cr', 'sold_cr',
            'adding', 'cutting', 'new', 'exits', 'holdings', 'unvalued']
    if sc is None or sc.empty:
        return pd.DataFrame(columns=cols)
    x = sc if 'house_kind' in sc else sc.assign(house_kind='mf')
    v = x['change_cr']
    x = x.assign(_b=v.clip(lower=0), _s=v.clip(upper=0), _add=x['change'].gt(0), _cut=x['change'].lt(0),
                 _new=x['status'].eq('new'), _exit=x['status'].eq('exit'), _hold=x['shares_end'].gt(0),
                 _unv=v.isna() & x['change'].ne(0))
    out = x.groupby(['month', 'amc', 'house_kind', 'scheme_key'], sort=False).agg(
        scheme=('scheme', 'first'), passive=('passive', 'max'), scheme_seen=('scheme_seen', 'first'),
        net_cr=('change_cr', 'sum'), bought_cr=('_b', 'sum'), sold_cr=('_s', 'sum'), adding=('_add', 'sum'),
        cutting=('_cut', 'sum'), new=('_new', 'sum'), exits=('_exit', 'sum'), holdings=('_hold', 'sum'),
        unvalued=('_unv', 'sum')).reset_index()
    for c in ('adding', 'cutting', 'new', 'exits', 'holdings', 'unvalued'):
        out[c] = out[c].astype(int)
    return out[cols]


SITE_MOVE_COLS = ['month', 'amc', 'house_kind', 'scheme_key', 'isin', 'shares_start', 'shares_end', 'change_cr', 'scheme_seen']


def scheme_moves(sc: pd.DataFrame, months: int = 12) -> pd.DataFrame:
    """The site's slim scheme table: active schemes only, rows that moved (change not zero), the last `months`
    month-ends, the columns the Funds page reads, as categories. A row that did not move says nothing a window needs:
    the shares at a window's start are the start of the first row that moved in it, and at its end the end of the last
    one. Index funds and ETFs stay in the full table (`mf_scheme_changes`)."""
    if sc is None or sc.empty:
        return pd.DataFrame(columns=SITE_MOVE_COLS)
    x = sc if 'house_kind' in sc else sc.assign(house_kind='mf')
    keep = sorted(x['month'].unique())[-months:]
    x = x[x['month'].isin(keep) & ~x['passive'].astype(bool) & x['change'].ne(0)][SITE_MOVE_COLS].copy()
    for c in ('month', 'amc', 'house_kind', 'scheme_key', 'isin', 'scheme_seen'):
        x[c] = x[c].astype(str).astype('category')
    x['change_cr'] = x['change_cr'].astype('float32')
    return x.reset_index(drop=True)


# ---- The scheme count check against AMFI ---------------------------------------------------------------------------
# AMFI publishes every scheme's NAV for a day (portal.amfiindia.com/DownloadNAVHistoryReport_Po.aspx?frmdt=30-Oct-2026),
# grouped under 'Open Ended Schemes ( Equity Scheme - Large Cap Fund )' and the fund house's name, one line per plan and
# option. The open-ended 'Equity Scheme' groups are the house's equity schemes that day (index funds, ETFs, hybrids and
# funds of funds have their own groups). Read on the month-end's last working day, it says how many equity schemes the
# house had, so a house whose file we read short of them shows.

AMFI_NAV_URL = 'https://portal.amfiindia.com/DownloadNAVHistoryReport_Po.aspx?frmdt={day}'
SHORT_SHARE = 0.8   # a house where we read fewer active equity schemes than this share of AMFI's count is flagged


def amfi_category(cat: str) -> str:
    """'equity', 'hybrid', 'index', 'etf', 'fof', 'debt', 'solution' or 'other' from an AMFI group heading."""
    c = str(cat or '').lower()
    for word, kind in (('exchange traded', 'etf'), ('etf', 'etf'), ('index fund', 'index'), ('fund of funds', 'fof'),
                       ('fof', 'fof'), ('equity scheme', 'equity'), ('elss', 'equity'), ('hybrid', 'hybrid'),
                       ('solution oriented', 'solution'), ('children', 'solution'), ('retirement', 'solution'),
                       ('debt', 'debt'), ('income', 'debt'), ('liquid', 'debt'), ('gilt', 'debt'), ('money market', 'debt')):
        if word in c:
            return kind
    return 'other'


def parse_amfi_nav(text: str) -> pd.DataFrame:
    """AMFI's NAV report (the day's file or NAVAll.txt) -> one row per plan: house (as AMFI names it), group heading,
    open_ended, category (`amfi_category`), scheme code, NAV name, date. The header row names the columns; a line that is
    not a heading, a house or a NAV row is skipped."""
    cols = ['house', 'group', 'open_ended', 'category', 'code', 'nav_name', 'date']
    rows, head, group, house = [], None, None, None
    for line in str(text).splitlines():
        t = line.strip()
        if not t:
            continue
        if ';' in t and head is None and t.lower().startswith('scheme code'):
            head = [h.strip().lower() for h in t.split(';')]
            continue
        if ';' not in t:
            if re.match(r'^(?:open|close|interval)[ -]?ended schemes', t, re.I) or t.lower().startswith('interval fund'):
                group, house = re.sub(r'\s+', ' ', t), None
            else:
                house = t
            continue
        if head is None or group is None or house is None:
            continue
        f = [x.strip() for x in t.split(';')]
        d = dict(zip(head, f))
        name = d.get('nav name') or d.get('scheme name')
        if not name or not f[0].isdigit():
            continue
        rows.append({'house': house, 'group': group, 'open_ended': group.lower().startswith('open'),
                     'category': amfi_category(group), 'code': f[0], 'nav_name': name, 'date': d.get('date')})
    return pd.DataFrame(rows, columns=cols)


def _hkey(name) -> str:
    return re.sub(r'\s+', ' ', re.sub(r'[^a-z0-9 ]', ' ', str(name or '').lower())).strip()


def amfi_schemes(nav: pd.DataFrame, houses: dict) -> pd.DataFrame:
    """One row per house and scheme from `parse_amfi_nav`: our house key (`houses`: key -> name as AMFI lists it,
    compared without case and punctuation), the scheme key (`scheme_key` with AMFI's house name), category, open_ended,
    plans listed. AMFI houses we do not collect are kept with a blank key."""
    cols = ['amc', 'house', 'scheme_key', 'scheme', 'category', 'open_ended', 'plans', 'date']
    if nav is None or nav.empty:
        return pd.DataFrame(columns=cols)
    by_name = {_hkey(v): k for k, v in houses.items()}
    x = nav.assign(amc=nav['house'].map(lambda h: by_name.get(_hkey(h))),
                   scheme_key=[scheme_key(n, h) for n, h in zip(nav['nav_name'], nav['house'])])
    out = x.groupby(['house', 'scheme_key', 'open_ended'], sort=False, dropna=False).agg(
        amc=('amc', 'first'), scheme=('nav_name', 'first'), category=('category', 'first'), plans=('code', 'nunique'),
        date=('date', 'first')).reset_index()
    return out[cols]


def scheme_coverage(lists: pd.DataFrame, amfi: pd.DataFrame | None, kinds: dict | None = None) -> pd.DataFrame:
    """Per house and month: schemes read in its file(s) (`scheme_list` rows), those holding equity, those holding equity
    and not index funds or ETFs (`active_equity_read`); and where AMFI's list for that month-end was read, the house's
    open-ended equity schemes on it (`amfi_equity`), how many of them we matched by name (`amfi_matched`), the names not
    matched, and `flag`: 'fewer schemes read' when we read under SHORT_SHARE of AMFI's count (counted, so a name we
    failed to match does not raise it), else blank. `amfi_equity` is blank where AMFI's list was not read or the house is
    not on it (pension funds are not); then only what we read is stated. Hybrid funds hold equity too and are in
    `active_equity_read`, not in AMFI's equity count, so a complete house reads at or above it."""
    cols = ['month', 'amc', 'house_kind', 'schemes_read', 'equity_schemes_read', 'active_equity_read', 'amfi_date',
            'amfi_equity', 'amfi_matched', 'amfi_not_matched', 'flag']
    if lists is None or lists.empty:
        return pd.DataFrame(columns=cols)
    kinds = kinds or {}
    rows = []
    for (mth, amc), g in lists.groupby(['month', 'amc'], sort=True):
        eq = g[g['equity_lines'].gt(0)]
        act = eq[~eq['passive'].astype(bool)]
        r = {'month': mth, 'amc': amc, 'house_kind': kinds.get(amc, 'mf'), 'schemes_read': int(g['scheme_key'].nunique()),
             'equity_schemes_read': int(eq['scheme_key'].nunique()), 'active_equity_read': int(act['scheme_key'].nunique()),
             'amfi_date': None, 'amfi_equity': None, 'amfi_matched': None, 'amfi_not_matched': None, 'flag': ''}
        a = amfi[(amfi['month'] == mth) & (amfi['amc'] == amc) & amfi['open_ended'] & amfi['category'].eq('equity')] \
            if amfi is not None and not amfi.empty else None
        if a is not None and len(a):
            ours = set(g['scheme_key'])
            hit = a['scheme_key'].isin(ours)
            r.update(amfi_date=a['date'].iloc[0], amfi_equity=int(a['scheme_key'].nunique()),
                     amfi_matched=int(a.loc[hit, 'scheme_key'].nunique()),
                     amfi_not_matched='; '.join(sorted(a.loc[~hit, 'scheme'].astype(str).unique()))[:2000])
            if r['active_equity_read'] < SHORT_SHARE * r['amfi_equity']:
                r['flag'] = 'fewer schemes read'
        rows.append(r)
    return pd.DataFrame(rows, columns=cols)
