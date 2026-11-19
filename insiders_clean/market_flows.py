"""Market-wide flows: what foreign portfolio investors, domestic institutions and mutual funds bought and sold.

Sources (each fetched and read from a real answer on 19 Nov 2026; fixtures in tests/fixtures/market_flows/):

- NSE `/api/fiidiiTradeReact` and `/api/fiidiiTradeNse` (the page www.nseindia.in/reports/fii-dii): the
  exchanges' provisional FII/FPI and DII cash-market buy, sell and net in Rs crore, same evening, compiled from the
  client category trading members report on T day. `React` is NSE, BSE and MSEI together; `Nse` is NSE alone. A list
  of two rows {category: 'DII'|'FII/FPI', date: '18-Nov-2026', buyValue, sellValue, netValue}. **Latest day only**:
  date parameters are ignored, so there is no history to backfill; each night keeps its own day.
- NSDL `fpi.nsdl.co.in/web/Reports/Archive.aspx` (an ASP.NET form: POST the page's own hidden fields with
  `hdnDate=DD-Mon-YYYY`): "Daily Trends in FPI Investments" from the 1st of that date's month up to it, one block
  per **reporting date** (custodians' reports; the trades are of the previous trading day(s)), by asset class
  (Equity, Debt-General Limit, Debt-VRR, Debt-FAR, Hybrid, Mutual Funds, AIFs) and route (Stock Exchange, Primary
  market & others; Mutual Funds by scheme type), gross purchases, gross sales and net in Rs crore, net in USD mn and
  the day's RBI rate, then "Total for {month}" and "Total for {year}" blocks. Settled figures, not provisional.
- NSDL `.../StaticReports/Fortnightly_Sector_wise_FII_Investment_Data/FIIInvestSector_{Mon}{DD}{YYYY}.html`
  (listed on `FPI_Fortnightly_Selection.aspx`, file names not regular: `June302026`, `July312025`): per BSE sector,
  AUC at the previous fortnight end, net investment in the previous and this fortnight and AUC at this fortnight end,
  each in INR crore and USD mn, 12 columns each (equity, debt general, VRR, FAR, hybrid, five mutual fund kinds,
  AIF, total).
- SEBI `sebiweb/other/OtherAction.do?doMfdTrendsSearch=yes` (POST `date=DD-MM-YYYY` with the page's own
  `currdate` and token, and a Referer: without one the site's firewall answers 530): "Daily Trends in Mutual Funds
  Investments" from the 1st of that date's month up to it, per trading date, Equity and Debt gross purchases, gross
  sales and net in Rs crore, then a Total. Custodians' reports; on 19 Nov 2026 the newest day was 04 Nov.

Negative numbers are written in brackets, `(4622.19)`. Every row's net is checked against buy less sell, and each
month's days against the source's own month total; a row or month that does not add up is reported, not kept quiet.
"""
from __future__ import annotations

import re
from datetime import date, datetime
from html import unescape

import pandas as pd

COLUMNS = ['date', 'source', 'segment', 'category', 'buy_cr', 'sell_cr', 'net_cr', 'provisional', 'date_basis']
SECTOR_COLUMNS = ['fortnight_end', 'period_start', 'sector', 'net_equity_cr', 'net_total_cr', 'net_equity_usd_mn',
                  'net_total_usd_mn', 'auc_equity_cr', 'auc_total_cr', 'prev_net_equity_cr', 'prev_period_start',
                  'prev_period_end']
NET_TOL = 0.02          # Rs crore: buy - sell may differ from the printed net by rounding only
MONTH_TOL = 1.0         # Rs crore: the days of a month against the source's month total

NSE_SEGMENTS = {'fiidiiTradeReact': 'cash_nse_bse_msei', 'fiidiiTradeNse': 'cash_nse'}
NSE_CATEGORY = {'FII/FPI': 'fpi', 'DII': 'dii'}

NSDL_ASSET = {'equity': 'equity', 'debt-general limit': 'debt_general', 'debt-vrr': 'debt_vrr', 'debt-far': 'debt_far',
              'hybrid': 'hybrid', 'mutual funds': 'mutual_funds', 'aifs': 'aif'}
NSDL_ROUTE = {'stock exchange': 'exchange', 'primary market & others': 'primary', 'sub-total': None}


def _num(text: str) -> float:
    """'1,234.50', '(4622.19)', '-1,098', '0' -> float. Anything else raises."""
    t = unescape(text).replace('\xa0', ' ').strip().replace(',', '')
    neg = t.startswith('(') and t.endswith(')')
    t = t.strip('()').strip()
    if not re.fullmatch(r'-?(\d+(\.\d+)?|\.\d+)', t):   # SEBI prints '.02' (July 2026)
        raise ValueError(f'not a number: {text!r}')
    v = float(t)
    return -v if neg else v


def _slug(text: str) -> str:
    return re.sub(r'[^a-z0-9]+', '_', text.lower()).strip('_')


def _rows(html: str):
    """[(cells, rowspans)] for every <tr>: the text of each cell and its rowspan."""
    out = []
    for tr in re.findall(r'<tr[^>]*>(.*?)</tr>', html, flags=re.S | re.I):
        cells, spans = [], []
        for attrs, inner in re.findall(r'<t[dh]([^>]*)>(.*?)</t[dh]>', tr, flags=re.S | re.I):
            cells.append(re.sub(r'\s+', ' ', unescape(re.sub(r'<[^>]+>', ' ', inner))).replace('\xa0', ' ').strip())
            m = re.search(r"rowspan\s*=\s*['\"]?(\d+)", attrs, flags=re.I)
            spans.append(int(m.group(1)) if m else 1)
        out.append((cells, spans))
    return out


def _check_net(df: pd.DataFrame, notes: list, label: str) -> pd.DataFrame:
    bad = (df['buy_cr'] - df['sell_cr'] - df['net_cr']).abs() > NET_TOL
    if bad.any():
        notes.append(f'{label}: {int(bad.sum())} row(s) where buy - sell is not net; dropped')
    return df[~bad].reset_index(drop=True)


# ---- NSE -------------------------------------------------------------------

def parse_nse(payload, endpoint: str) -> pd.DataFrame:
    """One NSE fiidii answer (a list of two dicts) -> rows. Raises on an unknown shape or category."""
    if endpoint not in NSE_SEGMENTS:
        raise ValueError(f'unknown NSE endpoint {endpoint}')
    if not isinstance(payload, list) or not payload:
        raise ValueError('NSE fiidii: expected a non-empty list')
    rows = []
    for r in payload:
        cat = NSE_CATEGORY.get(str(r.get('category', '')).strip())
        if cat is None:
            raise ValueError(f"NSE fiidii: unknown category {r.get('category')!r}")
        rows.append({'date': pd.Timestamp(datetime.strptime(r['date'].strip(), '%d-%b-%Y')), 'source': 'nse',
                     'segment': NSE_SEGMENTS[endpoint], 'category': cat, 'buy_cr': _num(str(r['buyValue'])),
                     'sell_cr': _num(str(r['sellValue'])), 'net_cr': _num(str(r['netValue'])),
                     'provisional': True, 'date_basis': 'trade'})
    return pd.DataFrame(rows, columns=COLUMNS)


# ---- NSDL daily ------------------------------------------------------------

def parse_nsdl_daily(html: str, notes: list | None = None) -> pd.DataFrame:
    """NSDL's Archive (or Monthly/Latest) page -> one row per reporting date, asset class and route.

    Segment: the asset class for its sub-total (`equity`, `debt_general`, ...), `{asset}_{route}` for a route
    (`equity_exchange`, `equity_primary`, `mutual_funds_equity_schemes`), `total` for the day's total. The month
    and year total blocks are read only to check the days against them."""
    notes = [] if notes is None else notes
    if 'Daily Trends in FPI Investments' not in html:
        raise ValueError('NSDL: no "Daily Trends in FPI Investments" table in the page')
    i = html.find('Daily Trends in FPI Investments')
    j = html.find('Daily Trends in FPI Derivative', i)
    html = html[html.rfind('<table', 0, i):j if j > 0 else len(html)]
    rows, totals = [], {}
    block = asset = None        # a reporting date, or a 'Total for ...' label
    for cells, _ in _rows(html):
        c = list(cells)
        if sum(bool(re.fullmatch(r'\(?-?[\d,]+(\.\d+)?\)?', x)) for x in c) < 4:
            continue            # notes, titles and headers
        if re.fullmatch(r'\d{2}-[A-Za-z]{3}-\d{4}', c[0]):
            block, c = pd.Timestamp(datetime.strptime(c[0], '%d-%b-%Y')), c[1:]
        elif c[0].startswith('Total for '):
            block, c = c[0][10:].strip(), c[1:]
        if c[0] == 'Total':
            if isinstance(block, pd.Timestamp):
                rows.append((block, 'total', *(_num(x) for x in c[1:4])))
            continue
        if c[0].lower() in NSDL_ASSET:
            asset, c = NSDL_ASSET[c[0].lower()], c[1:]
        elif len(c) > 5 and not re.fullmatch(r'Rs\.\s*[\d.]+|', c[5]):
            raise ValueError(f'NSDL: unknown asset class {c[0]!r}')
        if block is None or asset is None:
            raise ValueError(f'NSDL: a figure row before its date or asset class: {cells[:3]}')
        route = NSDL_ROUTE.get(c[0].lower(), _slug(c[0]))
        seg = asset if route is None else f'{asset}_{route}'
        buy, sell, net = (_num(x) for x in c[1:4])
        if isinstance(block, pd.Timestamp):
            rows.append((block, seg, buy, sell, net))
        else:
            totals.setdefault(block, {})[seg] = net
    df = pd.DataFrame(rows, columns=['date', 'segment', 'buy_cr', 'sell_cr', 'net_cr'])
    if df.empty:
        return pd.DataFrame(columns=COLUMNS)
    df['source'], df['category'], df['provisional'], df['date_basis'] = 'nsdl', 'fpi', False, 'reported'
    df = _check_net(df[COLUMNS], notes, 'nsdl')
    for month, segs in totals.items():
        if month.isdigit():
            continue    # the year's total: the page holds one month only
        days = df[(df['date'].dt.strftime('%B') == month) & (df['segment'] == 'equity')]
        if 'equity' in segs and abs(days['net_cr'].sum() - segs['equity']) > MONTH_TOL:
            notes.append(f'nsdl: {month} days add to {days["net_cr"].sum():.2f} equity net, NSDL total '
                         f'{segs["equity"]:.2f}: a day is missing or changed')
            df.attrs['short'] = True
    return df


# ---- NSDL fortnightly sectors ---------------------------------------------

_HEAD_DATE = r'([A-Za-z]+) (\d{1,2})(?:-(\d{1,2}))?, (\d{4})'


def _head_date(text: str) -> tuple[date, date]:
    m = re.search(_HEAD_DATE, text)
    if not m:
        raise ValueError(f'NSDL sectors: no date in {text!r}')
    mon, d1, d2, yr = m.groups()
    month = datetime.strptime(mon[:3], '%b').month
    a = date(int(yr), month, int(d1))
    return a, date(int(yr), month, int(d2)) if d2 else a


def parse_nsdl_sectors(html: str) -> pd.DataFrame:
    """One fortnightly sector report -> one row per sector (and the Grand Total as sector 'Grand Total').

    Columns per row: 8 groups of 12 (AUC previous, net previous fortnight, net this fortnight, AUC now; each INR
    crore then USD mn), each group equity first and total last. Raises if the header or a row is not that shape."""
    rows = _rows(html)
    head = next((c for c, _ in rows if len(c) == 6 and c[2].startswith('AUC as on')), None)
    if head is None or not (head[3].startswith('Net Investment') and head[4].startswith('Net Investment')
                            and head[5].startswith('AUC as on')):
        raise ValueError('NSDL sectors: header not AUC / Net / Net / AUC')
    prev_start, prev_end = _head_date(head[3])
    start, end = _head_date(head[4])
    auc_end, _ = _head_date(head[5])
    if auc_end != end:
        raise ValueError(f'NSDL sectors: AUC date {auc_end} is not the fortnight end {end}')
    out = []
    for cells, _ in rows:
        if len(cells) != 98 or cells[1] in ('Sectors', ''):
            continue
        try:
            v = [_num(x) for x in cells[2:]]
        except ValueError as exc:
            raise ValueError(f'NSDL sectors: {cells[1]}: {exc}') from exc
        g = [v[i * 12:(i + 1) * 12] for i in range(8)]
        out.append({'fortnight_end': pd.Timestamp(end), 'period_start': pd.Timestamp(start), 'sector': cells[1],
                    'net_equity_cr': g[4][0], 'net_total_cr': g[4][11], 'net_equity_usd_mn': g[5][0],
                    'net_total_usd_mn': g[5][11], 'auc_equity_cr': g[6][0], 'auc_total_cr': g[6][11],
                    'prev_net_equity_cr': g[2][0], 'prev_period_start': pd.Timestamp(prev_start),
                    'prev_period_end': pd.Timestamp(prev_end)})
    if not out or out[-1]['sector'] != 'Grand Total':
        raise ValueError('NSDL sectors: no sector rows ending in Grand Total')
    df = pd.DataFrame(out, columns=SECTOR_COLUMNS)
    body = df[df['sector'] != 'Grand Total']
    if abs(body['net_total_cr'].sum() - df['net_total_cr'].iloc[-1]) > 24:   # whole crores, rounded per sector
        raise ValueError('NSDL sectors: sectors do not add to the Grand Total')
    return df


def sector_options(html: str) -> list[tuple[date, str]]:
    """The fortnight list on FPI_Fortnightly_Selection.aspx -> [(fortnight end, report path)], newest first.
    The labels are not regular ('JUNE 30, 2026', 'Jul 15, 2023'); one (labelled 'Feb 28, 2022' between 2023 dates)
    is wrong, so the date is read from the file name when the label disagrees."""
    out = []
    for path, label in re.findall(r'<option[^>]*value="([^"]+)"[^>]*>([^<]+)', html):
        if 'FIIInvestSector_' not in path:
            continue
        m = re.match(r'([A-Za-z]+)\s+(\d{1,2}),\s*(\d{4})', label.strip())
        f = re.search(r'FIIInvestSector_([A-Za-z]+?)(\d{1,2})(\d{4})\.html', path)
        try:
            d = date(int(f.group(3)), datetime.strptime(f.group(1)[:3], '%b').month, int(f.group(2)))
        except (AttributeError, ValueError):
            if not m:
                continue
            d = date(int(m.group(3)), datetime.strptime(m.group(1)[:3], '%b').month, int(m.group(2)))
        out.append((d, path.replace('~/', '/web/', 1)))
    return out


# ---- SEBI ------------------------------------------------------------------

def parse_sebi(html: str, notes: list | None = None) -> pd.DataFrame:
    """SEBI's mutual fund trends page -> one row per trading date and segment (equity, debt), category mf."""
    notes = [] if notes is None else notes
    i = html.find('Daily Trends in Mutual Funds Investments')
    if i < 0:
        raise ValueError('SEBI: no "Daily Trends in Mutual Funds Investments" table in the page')
    j = html.find('Daily Trends in Mutual Funds Derivative', i)
    part = html[i:j if j > 0 else len(html)]
    rows, total = [], {}
    day = None
    for cells, _ in _rows(part):
        if not cells:
            continue
        c = list(cells)
        if re.fullmatch(r'\d{2} [A-Za-z]{3}, \d{4}', c[0]):
            day = pd.Timestamp(datetime.strptime(c[0], '%d %b, %Y'))
            c = c[1:]
        elif c[0] == 'Total':
            day = 'total'
            c = c[1:]
        if len(c) != 4 or c[0].lower() not in ('equity', 'debt') or day is None:
            continue
        buy, sell, net = (_num(x) for x in c[1:])
        if day == 'total':
            total[c[0].lower()] = net
        else:
            rows.append((day, c[0].lower(), buy, sell, net))
    df = pd.DataFrame(rows, columns=['date', 'segment', 'buy_cr', 'sell_cr', 'net_cr'])
    if df.empty:
        return pd.DataFrame(columns=COLUMNS)
    df['source'], df['category'], df['provisional'], df['date_basis'] = 'sebi', 'mf', False, 'trade'
    df = _check_net(df[COLUMNS], notes, 'sebi')
    for seg, net in total.items():
        got = df.loc[df['segment'] == seg, 'net_cr'].sum()
        if abs(got - net) > MONTH_TOL:
            notes.append(f'sebi: {seg} days add to {got:.2f}, SEBI total {net:.2f}: a day is missing or changed')
            df.attrs['short'] = True
    return df


# ---- the clean table -------------------------------------------------------

def merge(old: pd.DataFrame | None, new: pd.DataFrame, keys=('date', 'source', 'segment', 'category')) -> pd.DataFrame:
    """Rows of `new` replace rows of `old` with the same keys (a later fetch of the same day wins)."""
    frames = [f for f in (old, new) if f is not None and not f.empty]
    if not frames:
        return pd.DataFrame(columns=list(new.columns) if new is not None else COLUMNS)
    df = pd.concat(frames, ignore_index=True)
    return df.drop_duplicates(list(keys), keep='last').sort_values(list(keys)).reset_index(drop=True)


def build(archive: pd.DataFrame | None, since: str = '2025-10-08') -> pd.DataFrame:
    """The clean table from every archived row: product window, the clean columns, newest first."""
    if archive is None or archive.empty:
        return pd.DataFrame(columns=COLUMNS)
    df = archive.copy()
    df['date'] = pd.to_datetime(df['date'])
    df = df[df['date'] >= pd.Timestamp(since)]
    for c in ('buy_cr', 'sell_cr', 'net_cr'):
        df[c] = pd.to_numeric(df[c], errors='coerce').astype(float)
    df['provisional'] = df['provisional'].astype(bool)
    df = df.drop_duplicates(['date', 'source', 'segment', 'category'], keep='last')
    return df[COLUMNS].sort_values(['date', 'source', 'segment', 'category'],
                                   ascending=[False, True, True, True]).reset_index(drop=True)
