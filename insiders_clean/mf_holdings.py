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
other line is counted, not dropped silently.

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
    if value_unit not in VALUE_UNIT:
        raise ValueError(f'value_unit {value_unit!r}: one of {sorted(VALUE_UNIT)}')
    rows, report = [], {'workbooks': 0, 'sheets': 0, 'sheets_read': 0, 'skipped': {}, 'value_unit': value_unit}
    for name, data in _books(body, filename):
        report['workbooks'] += 1
        for sheet, srows in _sheets(name, data):
            report['sheets'] += 1
            got, why = parse_rows(sheet, srows)
            if why:
                report['skipped'][why] = report['skipped'].get(why, 0) + 1
                continue
            report['sheets_read'] += 1
            rows += got
    df = pd.DataFrame(rows, columns=['sheet', 'scheme', 'isin', 'name', 'quantity', 'value_lakh', 'pct_aum'])
    df['value_lakh'] = pd.to_numeric(df['value_lakh'], errors='coerce') / VALUE_UNIT[value_unit]
    report['lines'] = int(len(df))
    report['equity_lines'] = int(is_equity(df['isin']).sum()) if len(df) else 0
    report['equity_lines_no_quantity'] = int((is_equity(df['isin']) & df['quantity'].isna()).sum()) if len(df) else 0
    return df, report


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
