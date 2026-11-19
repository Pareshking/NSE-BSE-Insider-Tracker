"""Results: one quarter of an Indian financial year, a group of companies, what their results say (owner, 19 Nov 2026:
the page of the latest filings was "useless as it stands"; wanted: KPI cards for the period, a financial-year quarter,
market-cap and industry filters, a sortable table, the group's best and worst, and a roll-up by sector).

Built from the clean `results` table only (NSE integrated-filing XBRL, insiders_clean/results.py): one row per company
and quarter end (consolidated where both are filed), the year-ago quarter from our own history
(more_pages._latest_results). Market cap and its bucket from the price summary (insiders_clean/slim.py, by rank: 1-100
Large, 101-250 Mid, 251-500 Small, the rest Micro). Industry from `clean/current/industry.parquet` (macro, sector,
industry, basic industry) once it exists, else the security master's sector and industry; a level with no data is not
drawn. Nothing here cleans or fills a figure: a row whose figures cannot be right is held back with its reason
(results.doubt_reason), never altered.
"""
from __future__ import annotations

import pandas as pd
import streamlit as st
from data import store

from insiders_clean.results import doubt_reason
from insiders_clean.slim import BUCKETS
from screens import moves, proto
from screens.ctx import load, need_data
from ui import kit
from ui.kit import esc
from ui.table import Col, table

ALL = 'All'
# The industry levels, top down, with the label each filter carries.
LEVELS = (('macro', 'Macro sector'), ('sector', 'Sector'), ('industry', 'Industry'), ('basic_industry', 'Basic industry'))
# A quarter is the default only when at least this share of the busiest quarter's companies have filed it: a few early
# filers of a new quarter (December results in early January) are not "the latest quarter" yet.
MEANINGFUL_SHARE = 1 / 3
REAL_BASE = 1e8          # ₹10 Cr: a year-ago revenue under it makes +1,775% (Tarc, 12 Nov) and is not ranked
ROLLUP_MIN = 3           # a sector's median is shown when at least this many companies can be compared
TABLE_ROWS = 400


# ---- Financial-year quarters ------------------------------------------------------------------------------------------

def fy_quarter(period_end) -> tuple[int, int] | None:
    """(financial year, quarter) of an Indian financial year (April to March) for a quarter ending on `period_end`.
    The year is named by the March it ends in: 30 Jun 2026 is Q1 of FY27 (2027), 31 Mar 2027 is Q4 of FY27.
    A period ending in the first days of a month (a 52-week year closing on 2 Oct) belongs to the month before."""
    t = pd.to_datetime(period_end, errors='coerce')
    if pd.isna(t):
        return None
    t = t - pd.Timedelta(days=7)
    m = t.month
    return (t.year + 1 if m >= 4 else t.year), ((m - 4) % 12) // 3 + 1


def fy_label(fy: int) -> str:
    return f'FY{fy % 100:02d}'


def fy_long(fy: int) -> str:
    """FY27 (Apr 2026 – Mar 2027)."""
    return f'{fy_label(fy)} (Apr {fy - 1} – Mar {fy})'


def period_label(fy: int, q: int) -> str:
    return f'Q{q} {fy_label(fy)}'


def quarter_months(fy: int, q: int) -> str:
    """Jul–Sep 2026 for Q2 FY27."""
    start = pd.Timestamp(year=fy - 1, month=4, day=1) + pd.DateOffset(months=3 * (q - 1))
    end = start + pd.DateOffset(months=2)
    return f'{start:%b}–{end:%b %Y}'


def default_period(counts: dict) -> tuple[int, int] | None:
    """The latest (fy, q) whose company count is at least MEANINGFUL_SHARE of the busiest quarter's."""
    if not counts:
        return None
    bar = max(counts.values()) * MEANINGFUL_SHARE
    return max(k for k, n in counts.items() if n >= bar)


# ---- The rows ---------------------------------------------------------------------------------------------------------

def _num(s) -> pd.Series:
    return pd.to_numeric(s, errors='coerce')


def industry_map(industry: pd.DataFrame | None, securities: pd.DataFrame | None) -> tuple[pd.DataFrame, str]:
    """(isin + nse_symbol + whichever LEVELS hold data, source label). The four-level table when it has any level
    filled, else the security master's sector and industry; empty when neither has any."""
    for df, label in ((industry, 'industry classification'), (securities, 'security master (sector, industry)')):
        if df is None or df.empty or 'isin' not in df:
            continue
        levels = [lv for lv, _ in LEVELS if lv in df and df[lv].notna().any()]
        if df is securities:
            levels = [lv for lv in levels if lv in ('sector', 'industry')]
        if not levels:
            continue
        keep = ['isin'] + (['nse_symbol'] if 'nse_symbol' in df else []) + levels
        m = df[keep].copy()
        for lv in levels:   # blank text is no classification
            m[lv] = m[lv].where(m[lv].astype(str).str.strip().ne(''))
        return m.dropna(subset=levels, how='all').drop_duplicates('isin'), label
    return pd.DataFrame(columns=['isin']), ''


def prepare(r: pd.DataFrame, prices: pd.DataFrame | None, ind: pd.DataFrame | None) -> pd.DataFrame:
    """One row per company and quarter end (more_pages._latest_results) with the page's columns: fy, q, the figures
    compared (the half year for a half-year-only filing), profit YoY, margin, the doubt reason, swings, market cap and
    bucket, the industry levels."""
    if r is None or r.empty:
        return pd.DataFrame()
    r = r.copy()
    fq = r['_end'].map(fy_quarter)
    r = r[fq.notna()].copy()
    r['fy'] = [k[0] for k in fq[fq.notna()]]
    r['q'] = [k[1] for k in fq[fq.notna()]]
    half = r['half_year'].astype('boolean').fillna(False).astype(bool) if 'half_year' in r else pd.Series(False, index=r.index)
    pick = lambda q_col, h_col: _num(r[q_col]).where(~half, _num(r[h_col]) if h_col in r else float('nan'))  # noqa: E731
    r['half'] = half
    r['rev'] = pick('quarter_revenue', 'ytd_revenue')
    r['rev_yoy_'] = pick('rev_yoy', 'ytd_yoy')
    r['profit'] = pick('quarter_profit', 'ytd_profit')
    r['profit_y'] = pick('profit_year', 'ytd_profit_year')
    ok = r['profit_y'].gt(0) & r['profit'].notna()
    r['profit_yoy'] = ((r['profit'] / r['profit_y'] - 1) * 100).where(ok)
    r['margin'] = (r['profit'] / r['rev'] * 100).where(r['rev'].gt(0) & r['profit'].notna())
    r['base'] = r['rev'] / (1 + r['rev_yoy_'] / 100)
    r['doubt'] = [doubt_reason(a, b, c, d) for a, b, c, d in zip(r['rev'], r['profit'], r['profit_y'], r['rev_yoy_'])]
    r['to_profit'] = r['profit_y'].lt(0) & r['profit'].ge(0)
    r['to_loss'] = r['profit_y'].ge(0) & r['profit'].lt(0)
    if prices is not None and not prices.empty and 'isin' in prices:
        p = prices.drop_duplicates('isin').set_index('isin')
        for c in ('market_cap', 'mcap_rank', 'mcap_bucket'):
            r[c] = r['isin'].map(p[c]) if c in p else None
    else:
        r['market_cap'], r['mcap_rank'], r['mcap_bucket'] = float('nan'), float('nan'), None
    if ind is not None and not ind.empty:
        levels = [lv for lv, _ in LEVELS if lv in ind]
        by_isin = ind.set_index('isin')
        sym = r['symbol'].astype(str).str.upper() if 'symbol' in r else pd.Series('', index=r.index)
        by_sym = (ind.dropna(subset=['nse_symbol']).assign(_s=lambda d: d['nse_symbol'].astype(str).str.upper())
                  .drop_duplicates('_s').set_index('_s') if 'nse_symbol' in ind else None)
        for lv in levels:
            v = r['isin'].map(by_isin[lv])
            if by_sym is not None:   # an ISIN the classification does not have, by the NSE symbol
                v = v.fillna(sym.map(by_sym[lv]))
            r[lv] = v
    return r


def cascade(df: pd.DataFrame, levels: list[str], picks: dict) -> tuple[list[tuple[str, list[str]]], pd.DataFrame]:
    """The options of each industry level within the levels picked above it, and the rows left. A pick that is not
    among its level's options (the level above changed) counts as All."""
    out, cur = [], df
    for lv in levels:
        opts = sorted(cur[lv].dropna().astype(str).unique()) if lv in cur else []
        out.append((lv, opts))
        p = picks.get(lv)
        if p and p != ALL and p in opts:
            cur = cur[cur[lv].astype(str) == p]
    return out, cur


def apply_filters(df: pd.DataFrame, fy: int, q: int, size: str = ALL, picks: dict | None = None,
                  levels: list[str] | None = None) -> pd.DataFrame:
    """The rows of one financial-year quarter, one market-cap bucket (All: every row, those with no market cap too),
    the industry picks."""
    if df is None or df.empty:
        return pd.DataFrame()
    x = df[(df['fy'] == fy) & (df['q'] == q)]
    if size and size != ALL:
        x = x[x['mcap_bucket'] == size]
    return cascade(x, levels or [lv for lv, _ in LEVELS if lv in x], picks or {})[1]


def _median(s: pd.Series) -> float | None:
    s = s.dropna()
    return float(s.median()) if len(s) else None


def kpis(df: pd.DataFrame) -> dict:
    """The group's figures. Held-back rows (doubt) count only as held back; a half-year-only filing counts as
    reported, not in the quarter's growth. Revenue growth needs a year-ago quarter with revenue above zero; profit
    growth a year-ago profit above zero (a loss a year ago is a swing, not a growth rate)."""
    if df is None or df.empty:
        return {'reported': 0, 'held': 0, 'half': 0, 'rev_n': 0, 'rev_up': 0, 'rev_median': None, 'profit_n': 0,
                'profit_up': 0, 'profit_median': None, 'to_profit': 0, 'to_loss': 0, 'no_revenue': 0}
    held = df['doubt'].ne('')
    q = df[~held & ~df['half']]
    rev, prof = q['rev_yoy_'].dropna(), q['profit_yoy'].dropna()
    return {'reported': int(df['isin'].nunique()), 'held': int(held.sum()), 'half': int((~held & df['half']).sum()),
            'rev_n': len(rev), 'rev_up': int(rev.gt(0).sum()), 'rev_median': _median(rev),
            'profit_n': len(prof), 'profit_up': int(prof.gt(0).sum()), 'profit_median': _median(prof),
            'to_profit': int(q['to_profit'].sum()), 'to_loss': int(q['to_loss'].sum()),
            'no_revenue': int(q['rev'].isna().sum())}


def movers(df: pd.DataFrame, n: int = 5) -> tuple[pd.DataFrame, pd.DataFrame]:
    """(most grown, most shrunk) by revenue YoY, on a year-ago quarter of ₹10 Cr or more, held-back rows left out."""
    if df is None or df.empty:
        return pd.DataFrame(), pd.DataFrame()
    x = df[df['doubt'].eq('') & ~df['half'] & df['base'].ge(REAL_BASE) & df['rev_yoy_'].notna()]
    return (x[x['rev_yoy_'].gt(0)].sort_values('rev_yoy_', ascending=False).head(n),
            x[x['rev_yoy_'].lt(0)].sort_values('rev_yoy_').head(n))


def rollup(df: pd.DataFrame, level: str) -> pd.DataFrame:
    """Per value of `level`: companies, those compared, median revenue and profit YoY, how many grew; groups with
    fewer than ROLLUP_MIN compared companies are left out (they are in the table)."""
    cols = ['group', 'companies', 'compared', 'rev_median', 'profit_median', 'rev_up']
    if df is None or df.empty or level not in df:
        return pd.DataFrame(columns=cols)
    x = df[df['doubt'].eq('') & ~df['half'] & df[level].notna()]
    rows = []
    for g, d in x.groupby(level):
        rev = d['rev_yoy_'].dropna()
        if len(rev) < ROLLUP_MIN:
            continue
        rows.append({'group': str(g), 'companies': int(d['isin'].nunique()), 'compared': len(rev),
                     'rev_median': float(rev.median()), 'profit_median': _median(d['profit_yoy']),
                     'rev_up': f'{int(rev.gt(0).sum())} of {len(rev)}'})
    return pd.DataFrame(rows, columns=cols).sort_values('rev_median', ascending=False).reset_index(drop=True)


# ---- The page ---------------------------------------------------------------------------------------------------------

_CACHE: dict = {}


def _rows(ctx) -> pd.DataFrame:
    """Every company-quarter with its comparisons, built once per data load (ctx is shared and rebuilt every 10
    minutes)."""
    from screens import more_pages
    key = (id(ctx.results), id(ctx.prices), id(ctx.securities), str(ctx.ref))
    if key not in _CACHE:
        ind, src = industry_map(_industry_table(), ctx.securities)
        r = more_pages._latest_results(ctx, days=100_000) if ctx.ref is not None else pd.DataFrame()
        _CACHE.clear()
        _CACHE[key] = (prepare(r, ctx.prices, ind), src)
    return _CACHE[key]


def _industry_table() -> pd.DataFrame:
    try:
        return store.table('industry')
    except Exception:  # noqa: BLE001 -- the table is optional until its first write
        return pd.DataFrame()


def _keep(key: str, options: list, fallback) -> None:
    """A widget's remembered value stays only while it is still an option."""
    if st.session_state.get(key) not in options:
        st.session_state[key] = fallback


def _pct(v) -> str:
    return '–' if v is None else f'{v:+.1f}%'


ICON = {'up': '↑', 'down': '↓', 'warn': '!'}   # as ui/ds.stats draws them


def _kpi_html(cells: list[tuple[str, str, str, str]]) -> str:
    """The KPI cards of ui/ds.stats, three to a row (six cards: two even rows)."""
    out = []
    for label, value, note, tone in cells:
        icon = f'<span class="ic {tone}">{ICON[tone]}</span>' if tone in ICON else ''
        out.append(f'<div class="kpi"><div class="l">{icon}{esc(label)}</div><b>{esc(value)}</b><span class="s">{esc(note)}</span></div>')
    return '<div class="ds-kpis n3">' + ''.join(out) + '</div>'


def _names(df: pd.DataFrame, names: dict, n: int = 3) -> str:
    return proto._names_list([str(names.get(x.get('isin')) or x.get('company') or x.get('symbol') or '')
                              for x in df.head(n).to_dict('records')], n)


def _col(df: pd.DataFrame, c: str) -> pd.Series:
    return df[c] if c in df else pd.Series(None, index=df.index, dtype=object)


def _name_col(df: pd.DataFrame, names: dict) -> list[str]:
    return [str(names.get(i) or c or s or '') for i, c, s in zip(df['isin'], _col(df, 'company'), _col(df, 'symbol'))]


def _first_filled(df: pd.DataFrame, cols: list[str]) -> pd.Series:
    """Per row, the first of `cols` that holds a value (the deepest industry level filed)."""
    out = pd.Series(None, index=df.index, dtype=object)
    for c in cols:
        out = out.where(out.notna(), df[c])
    return out


def _table_rows(df: pd.DataFrame, names: dict, levels: list[str]) -> pd.DataFrame:
    """The table's columns: the company cell (with its size bucket), the quarter, the deepest industry level with the
    sector under it, the marks; largest company first."""
    deep = list(reversed(levels))
    top = 'sector' if 'sector' in levels else (levels[0] if levels else None)
    derived = (df['quarter_derived'].astype('boolean').fillna(False) if 'quarter_derived' in df
               else pd.Series(False, index=df.index))
    out = df.assign(
        name=_name_col(df, names),
        nse_symbol=_col(df, 'symbol'),
        mk_bucket=df['mcap_bucket'],
        period=[f'{period_label(f, q)} to {kit.day(e, with_year=False)} · {"consolidated" if c else "standalone"}'
                for f, q, e, c in zip(df['fy'], df['q'], df['_end'], df['_cons'])],
        ind=_first_filled(df, deep),
        ind_sub=(df[top] if top and len(levels) > 1 else None),
        notes=[[t for t, on in (('Back to profit', a), ('Into loss', b), ('Derived', d), ('Half year', h),
                                ('No revenue line', n)) if on]
               for a, b, d, h, n in zip(df['to_profit'], df['to_loss'], derived, df['half'], df['rev'].isna())])
    return out.sort_values('market_cap', ascending=False, na_position='last')


def render():
    ctx = load()
    if not need_data(ctx):
        return
    rows, source = _rows(ctx)
    _, _, names = moves.lookups(ctx)
    proto._strip(ctx, ['NSE integrated filing XBRL', 'year-ago quarter from our own history (filings from Apr 2025)',
                       f'industry: {source}' if source else 'industry: not in the data'])
    if rows.empty:
        st.html('<div class="head ds-head dt-head"><h1>Results</h1></div>'
                f'<p class="dt-empty">No quarterly results in the data.{proto._unconfirmed("results")}</p>')
        return
    counts = rows.groupby(['fy', 'q'])['isin'].nunique().to_dict()
    d_fy, d_q = default_period(counts)
    fys = sorted({f for f, _ in counts}, reverse=True)

    top = st.container()   # the headline goes above the filters it depends on
    c1, c2, c3 = st.columns([1.5, 1.6, 2.4], vertical_alignment='bottom')
    _keep('rs_fy', fys, d_fy)
    with c1:
        fy = st.selectbox('Financial year', fys, format_func=fy_long, key='rs_fy')
    qs = sorted(q for f, q in counts if f == fy)
    _keep('rs_q', qs, d_q if fy == d_fy and d_q in qs else qs[-1])
    with c2:
        q = st.segmented_control('Quarter', qs, format_func=lambda v: f'Q{v}', key='rs_q', required=True)
    has_mcap = rows['mcap_bucket'].notna().any()
    size = ALL
    if has_mcap:
        _keep('rs_size', [ALL, *BUCKETS], ALL)
        with c3:
            size = st.segmented_control('Market cap', [ALL, *BUCKETS], key='rs_size', required=True) or ALL
    period = rows[(rows['fy'] == fy) & (rows['q'] == q)]
    sized = period if size == ALL else period[period['mcap_bucket'] == size]
    levels = [lv for lv, _ in LEVELS if lv in period and period[lv].notna().any()]
    picks, cur = {}, sized
    if levels:
        cols = st.columns(len(levels))
        for (lv, label), col in zip([(lv, lb) for lv, lb in LEVELS if lv in levels], cols):
            opts = sorted(cur[lv].dropna().astype(str).unique())
            key = f'rs_{lv}'
            _keep(key, [ALL, *opts], ALL)
            with col:
                picks[lv] = st.selectbox(label, [ALL, *opts], key=key)
            if picks[lv] != ALL:
                cur = cur[cur[lv].astype(str) == picks[lv]]
    group = cur
    k = kpis(group)
    label = period_label(fy, q)
    chosen = [p for p in picks.values() if p != ALL]
    who = ' · '.join(([size] if size != ALL else []) + chosen) or 'all companies'
    head = (f'{label}: revenue up at <b>{k["rev_up"]:,}</b> of {k["rev_n"]:,} companies, median <b>{_pct(k["rev_median"])}</b>'
            if k['rev_n'] else f'{label}: no company in this group can be compared with a year ago yet')
    top.html(f'<div class="head ds-head dt-head"><h1>{head}</h1>'
            f'<p class="dt-dek">{esc(quarter_months(fy, q))} · {esc(who)} · {k["reported"]:,} companies filed '
            f'(of {counts.get((fy, q), 0):,} in the data for this quarter)</p></div>')
    if group.empty:
        st.html(f'<p class="dt-empty">No results for {esc(label)} in this group.{proto._unconfirmed("results")}</p>')
        return
    st.html(_kpi_html([
        ('Reported', f'{k["reported"]:,}', f'companies filed {label}' + (f', {k["no_revenue"]:,} without a revenue line' if k['no_revenue'] else ''), ''),
        ('Revenue grew YoY', f'{k["rev_up"]:,} of {k["rev_n"]:,}', 'with the year-ago quarter in our history', 'up' if k['rev_up'] else ''),
        ('Median revenue YoY', _pct(k['rev_median']), f'across {k["rev_n"]:,} companies', ''),
        ('Profit grew YoY', f'{k["profit_up"]:,} of {k["profit_n"]:,}', f'median {_pct(k["profit_median"])}, year-ago profit above zero', 'up' if k['profit_up'] else ''),
        ('Swung', f'{k["to_profit"]:,} · {k["to_loss"]:,}', 'to profit · to loss, against the year-ago quarter', ''),
        ('Held back', f'{k["held"]:,}', 'figures that cannot be right as filed', 'warn' if k['held'] else '')]))

    up, down = movers(group)
    proto._qa('Who grew most, and who shrank most?',
              (f'Grew most: {_names(up, names)}' if len(up) else 'No company grew on a year-ago quarter of ₹10 Cr or more')
              + (f'; shrank most: {_names(down, names)}' if len(down) else ''),
              'Revenue against the same quarter a year ago, where that quarter was ₹10 Cr or more. Against a year ago, '
              'not against analysts\' estimates: there are no estimates in our data.', anchor='movers')
    clean_q = group['doubt'].eq('') & ~group['half']   # as the KPI counts them
    back, into = group[group['to_profit'] & clean_q], group[group['to_loss'] & clean_q]
    proto._qa('Who swung to profit, who into loss?',
              (f'Back to profit: {_names(back.sort_values("market_cap", ascending=False), names)}' if len(back) else 'None back to profit')
              + (f'; into loss: {_names(into.sort_values("market_cap", ascending=False), names)}' if len(into) else ''),
              f'{len(back)} back to profit and {len(into)} into loss against the year-ago quarter; the largest companies named.',
              anchor='swings')

    shown = _table_rows(group[group['doubt'].eq('')], names, levels)
    proto._qa('Every result in this group', f'{len(shown):,} companies, largest first',
              'Click a column to sort it. Revenue and profit are the quarter\'s, as filed; YoY against the same quarter a '
              'year ago; margin is profit over revenue.', anchor='table')
    # the quarter and basis under the company name: every row is the chosen quarter, and the table fits the page
    table(shown, [Col('name', 'Company', 'co2', sub='period'),
                  Col('rev', 'Revenue', 'money'), Col('rev_yoy_', 'Revenue YoY', 'spct'),
                  Col('profit', 'Profit', 'money'), Col('profit_yoy', 'Profit YoY', 'spct'),
                  Col('margin', 'Margin', 'pct', phone=False), Col('market_cap', 'Market cap', 'money', phone=False),
                  Col('ind', 'Industry', sub='ind_sub', phone=False, wrap=True), Col('notes', '', 'tags', phone=False)],
          limit=TABLE_ROWS, height=720, key=f'rs_{fy}_{q}_{size}_{"|".join(chosen)}', keep_empty=True)

    deeper = [lv for lv in levels if picks.get(lv, ALL) == ALL]
    by = deeper[0] if deeper else None
    if by:
        ru = rollup(group, by)
        by_label = dict(LEVELS)[by]
        proto._qa(f'Which {by_label.lower()} grew most?',
                  (f'{esc(ru.iloc[0]["group"])}, median {_pct(ru.iloc[0]["rev_median"])}; slowest {esc(ru.iloc[-1]["group"])}, '
                   f'{_pct(ru.iloc[-1]["rev_median"])}' if len(ru) > 1 else 'Too few companies to compare'),
                  f'Median revenue and profit YoY by {by_label.lower()} for {label}; groups with fewer than {ROLLUP_MIN} '
                  'companies compared with a year ago are left out (they are in the table above).', anchor='rollup')
        if len(ru):
            table(ru, [Col('group', by_label), Col('companies', 'Companies', 'num'), Col('rev_median', 'Median revenue YoY', 'spct'),
                       Col('profit_median', 'Median profit YoY', 'spct'), Col('rev_up', 'Revenue grew', phone=False)],
                  limit=100, height=560, key=f'rs_roll_{by}_{fy}_{q}_{size}', keep_empty=True)

    held = group[group['doubt'].ne('')]
    if len(held):
        st.html('<h2 class="dt-h2" id="held">Held back for a look <span>figures that cannot be right as filed or read</span></h2>')
        table(held.assign(name=_name_col(held, names), nse_symbol=_col(held, 'symbol'), mk_bucket=held['mcap_bucket']),
              [Col('name', 'Company', 'co2'), Col('doubt', 'Why', wrap=True), Col('rev', 'Revenue', 'money'),
               Col('profit', 'Profit', 'money'), Col('profit_y', 'Year-ago profit', 'money')],
              limit=60, height=420, key=f'rs_held_{fy}_{q}', keep_empty=True)
    st.html('<p class="dt-foot">One row per company and quarter, consolidated where both are filed. A dash: the year-ago '
            'quarter is not in our history, or the filing has no revenue line under the Ind AS names (banks, NBFCs and '
            'insurers file theirs under other names; marked "No revenue line"). "Derived": the filing gives only its half year; the quarter is that '
            'less the June quarter filed before. "Half year": no quarter could be derived, so the half year is compared '
            'with the half year a year earlier; such rows are not in the KPI counts. Market-cap bucket by rank of NSE '
            'market cap (1-100 Large, 101-250 Mid, 251-500 Small, the rest Micro), estimated by us, not AMFI\'s list; '
            f'companies with no market cap show under All only. Industry from the {esc(source or "—")}.</p>')
