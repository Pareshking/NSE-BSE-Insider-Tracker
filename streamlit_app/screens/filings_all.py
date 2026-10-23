"""Filings: every filing and deal in one list, newest first (owner, 21 Oct 2026).

Insider filings (open market and off-market kinds, pledges, holding-only),
bulk and block deals, SAST Regulation 29 disclosures (NSE and BSE), preferential
issues, rights issues, QIPs, buybacks and corporate actions. One row per real
filing: the primary copy of an insider filing or deal (a filing on NSE and BSE
shows once), NSE's SAST disclosure or action plus the BSE ones NSE has not got.
A bulk deal that is the same trade as an insider's own filing is shown once,
under the insider (audit D6). Rows the cleaner held back appear only under
"Held back", each with its reason. Every row opens to the facts of its filing.

Numbers come from the builders the other pages use (screens/ctx.py issue rows,
screens/buybacks.py), so an offer price is put on today's split basis the same
way everywhere (audit W9) and Amount has one meaning (W11). Replaces Insider &
promoter trades, Other filings (SAST, transfers), Bulk & block deals' list and
the issue, buyback and corporate-action lists of Capital raises."""
from __future__ import annotations

import numpy as np
import pandas as pd
import streamlit as st
from data import store
from ui import kit
from ui.table import facts

from insiders_clean import participants, signals
from insiders_clean.calendar import DISCLOSURE_LIMIT_SESSIONS
from screens import buybacks, filings_rules
from screens.ctx import (ALLOTTEE_LABEL, flag_words, issue_rows, late_text, load, lock_in_calendar, need_data, pre_public_move,
                         qip_rows, rights_rows, split_since, window_text, with_flags, with_prices)

# One pill per kind of money event (docs/DESIGN_V3.md, owner 23 Oct): each has its own columns. 'All' stays the
# mixed feed of seven; 'Other filings' holds what is not a money decision (ESOP, gifts, splits, bonuses, dividends).
KINDS = ['All', 'Insider trades', 'Deals', 'Stake changes', 'Preferential', 'Rights', 'QIPs', 'Buybacks', 'Pledges',
         'Upcoming', 'Other filings', 'Held back']
UPCOMING_DAYS = 60
MEETING_WORDS = {'fund_raising': 'fund raising', 'buyback': 'a buyback', 'preferential': 'a preferential issue',
                 'rights': 'a rights issue'}
PERIODS = {7: '7 days', 30: '30 days', 90: '90 days', 365: '1 year'}
ROLES = ['Promoter', 'Director/KMP', 'Others']
MIN_VALUE = {0: 'Any value', 1e6: '₹10 L+', 1e7: '₹1 Cr+', 1e8: '₹10 Cr+', 1e9: '₹100 Cr+'}
LIMIT = 200

# Insider `kind` (insiders_clean/insider.py _MODE_RULES) in plain words.
KIND_WORDS = {
    'market': 'Open market', 'esop': 'ESOP', 'gift': 'Gift', 'inter_se': 'Inter-se transfer',
    'off_market': 'Off-market transfer', 'pledge_create': 'Pledge created', 'pledge_revoke': 'Pledge released',
    'pledge_invoke': 'Pledge invoked', 'holding_only': 'Holding disclosed, no trade', 'scheme': 'Scheme of arrangement',
    'conversion': 'Conversion (warrants)', 'offer_for_sale': 'Offer for sale', 'preferential': 'Preferential allotment',
    'rights': 'Rights', 'bonus': 'Bonus', 'buyback': 'Buyback', 'transmission': 'Transmission or inheritance',
    'allotment': 'Allotment', 'other': 'Other, as filed', 'unrecognised': 'Mode not recognised', 'missing': 'Mode not stated',
}
FEED_WORDS = {'bulk': 'Bulk deal', 'block': 'Block deal', 'block,bulk': 'Bulk and block deal'}
REG_WORDS = {'Reg29(1)': 'Stake crossed 5%', 'Reg29(2)': 'Stake moved 2% or more'}
ACTION_WORDS = {'rights': 'Rights record date', 'bonus': 'Bonus', 'split': 'Split', 'dividend': 'Dividend'}
HOLDING_CHECK = {'match': 'matches the shares traded', 'differs': "doesn't match the shares traded",
                 'against_side': 'moves against the side', 'against_side_and_differs': "moves against the side, size doesn't match",
                 'not_filed': 'holding or shares not filed'}
PRICE_CHECK = {'inside': "inside the day's range", 'below': "a little below the day's range",
               'above': "a little above the day's range", 'far_below': "far below the day's range",
               'far_above': "far above the day's range", 'power_of_ten': 'off by a power of ten',
               'swapped': 'shares and value swapped'}
LINK_STATUS = {'linked': 'matched to its approval', 'ambiguous': 'more than one possible approval',
               'no_in_principle_in_data': 'approval not in the filings we hold',
               'more_shares_than_approved': 'allots more shares than the only approval proposed'}
COLUMNS = ['_src', '_i', 'group', 'held', 'made_public', 'day_note', 'company', 'nse_symbol', 'isin', 'listed_on', 'who',
           'client_id', 'who_sub', 'what', 'what_sub', 'side', 'value', 'pct_of_mcap', 'role', 'is_mm', 'also_filed']


# ---- small helpers -------------------------------------------------------------------------------

def _b(s) -> pd.Series:
    return s.astype('boolean').fillna(False) if isinstance(s, pd.Series) else s


def _col(df: pd.DataFrame, c: str, default=None) -> pd.Series:
    return df[c] if c in df else pd.Series(default, index=df.index, dtype=object)


def _num(v):
    return kit._finite(v)


def _d(v) -> str:
    t = pd.to_datetime(v, errors='coerce')
    return '' if pd.isna(t) else kit.day(t)


def _span(a, b) -> str:
    a, b = _d(a), _d(b)
    return a if not b or a == b else (f'{a} to {b}' if a else b)


def _shares(v) -> str:
    return '' if _num(v) is None else kit.shares(v)


def _price(v) -> str:
    return '' if _num(v) is None else kit.price(v)


def _money(v) -> str:
    return '' if _num(v) is None else kit.rupees(v)


def _pct(v, signed=False) -> str:
    return '' if _num(v) is None else kit.pct(v, 2, signed=signed)


def _after(n, what: str) -> str:
    """'same session' or '3 sessions after the trade' (trading sessions, as the cleaner counts them)."""
    return 'same session' if int(n) == 0 else f'{kit.sessions_text(n)} after {what}'


def _txt(v) -> str:
    return '' if v is None or (not isinstance(v, (list, tuple)) and pd.isna(v)) else str(v).strip()


def _role_key(person_role: pd.Series) -> pd.Series:
    return person_role.map(lambda r: 'Promoter' if r in signals.PROMOTER_ROLES
                           else 'Director/KMP' if r in ('director', 'kmp') else 'Others')


def _names(ctx) -> pd.Series:
    """ISIN -> the company's display name from the security master."""
    sec = ctx.securities
    if sec is None or sec.empty or 'display_name' not in sec:
        return pd.Series(dtype=object)
    return sec.dropna(subset=['isin']).drop_duplicates('isin').set_index('isin')['display_name']


def _name(df: pd.DataFrame, names: pd.Series) -> pd.Series:
    filed = _col(df, 'company')
    return _col(df, 'isin').map(names).fillna(filed) if len(names) else filed


def _frame(src: str, df: pd.DataFrame, **cols) -> pd.DataFrame:
    out = pd.DataFrame({'_src': src, '_i': df.index}, index=df.index)
    for c in COLUMNS[2:]:
        v = cols.get(c)
        out[c] = v if v is not None else None
    return out.reset_index(drop=True)


# ---- one source at a time -> the common columns ------------------------------------------------

def _insider(ctx, since) -> tuple[pd.DataFrame, pd.DataFrame]:
    t = ctx.trades
    t = t[_b(t['is_primary'])]
    seen = pd.to_datetime(t['broadcast_date'], errors='coerce')
    t = t[seen >= since].copy()
    if t.empty:
        return t, pd.DataFrame(columns=COLUMNS)
    kind = t['kind'].astype(str)
    market = _b(t['is_market'])
    group = np.select([market.to_numpy(), kind.str.startswith('pledge').to_numpy()], ['Insider market', 'Pledges'],
                      'Insider other')
    return t, _frame('insider', t, group=group, held=_b(t['needs_review']),
                     made_public=pd.to_datetime(t['broadcast_date'], errors='coerce'), company=t['company'],
                     nse_symbol=t['nse_symbol'].fillna(t['symbol']), isin=t['isin'], listed_on=t['listed_on'],
                     who=t['person_name'], client_id=t['person_id'], who_sub=t['person_role'].map(kit.role),
                     what=kind.map(KIND_WORDS).fillna(kind.str.replace('_', ' ').str.capitalize()), side=t['side'],
                     value=pd.to_numeric(t['value'], errors='coerce'),
                     pct_of_mcap=pd.to_numeric(t['pct_of_mcap'], errors='coerce'),
                     role=_role_key(t['person_role']), is_mm=False, also_filed=False)


def _deals(ctx, since) -> tuple[pd.DataFrame, pd.DataFrame]:
    d = ctx.deals
    if d is None or d.empty:
        return pd.DataFrame(), pd.DataFrame(columns=COLUMNS)
    d = d[_b(d['is_primary']) & (pd.to_datetime(d['date'], errors='coerce') >= since)].copy()
    if d.empty:
        return d, pd.DataFrame(columns=COLUMNS)
    also = signals.deals_also_filed(d, ctx.trades)
    d['_also'] = also
    # The client's role in that company, when the same id filed as an insider there (one key space, as in
    # signals.handshakes); everyone else is "Others".
    t = ctx.trades.dropna(subset=['isin', 'person_id']).drop_duplicates(['isin', 'person_id'], keep='last')
    roles = dict(zip(zip(t['isin'], t['person_id']), _role_key(t['person_role'])))
    typ = _col(d, 'client_type').map(lambda k: participants.TYPES.get(k, '') if isinstance(k, str) else '')
    unsure = _col(d, 'client_type_confidence').eq('low')
    return d, _frame('deal', d, group='Deals', held=_b(_col(d, 'needs_review', False)), made_public=d['date'],
                     company=d['company'], nse_symbol=d['nse_symbol'].fillna(d['symbol']), isin=d['isin'],
                     listed_on=d['listed_on'], who=d['client_name'], client_id=d['client_id'],
                     who_sub=typ.where(~unsure | typ.eq(''), typ + ' (by name, unsure)'),
                     what=d['feeds'].map(FEED_WORDS).fillna('Bulk or block deal'),
                     what_sub=also.map({True: 'Same trade as an insider filing', False: ''}), side=d['side'],
                     value=pd.to_numeric(d['value'], errors='coerce'),
                     pct_of_mcap=pd.to_numeric(d['pct_of_mcap'], errors='coerce'),
                     role=[roles.get((i, c), 'Others') for i, c in zip(d['isin'], d['client_id'])],
                     is_mm=_b(_col(d, 'client_is_market_maker', False)), also_filed=also)


def _sast(ctx, since, names, known) -> tuple[pd.DataFrame, pd.DataFrame]:
    s = ctx.sast
    if s is None or s.empty:
        return pd.DataFrame(), pd.DataFrame(columns=COLUMNS)
    seen = pd.to_datetime(s['broadcast_ts'], errors='coerce', format='mixed', dayfirst=True)
    s = s[seen >= since].copy()
    s['_seen'] = seen
    if s.empty:
        return s, pd.DataFrame(columns=COLUMNS)
    act = s['action_type'].astype(str).str.lower()
    prom = _b(s['is_promoter'])
    after = pd.to_numeric(s['post_stake_pct'], errors='coerce')
    traded = pd.to_numeric(s['percent_equity_traded'], errors='coerce')
    sub = [' · '.join(x for x in (f'{_pct(a, True)} of capital' if _num(a) is not None else '',
                                  f'{_pct(b)} after' if _num(b) is not None else '') if x) for a, b in zip(traded, after)]
    return s, _frame('sast', s, group='SAST', held=False, made_public=s['_seen'].dt.normalize(),
                     company=_name(s, names), nse_symbol=s['symbol'], isin=s['isin'] if 'isin' in s else None,
                     listed_on=_col(s, 'listed_on', 'nse'), who=s['acquirer_name'],
                     client_id=s['acquirer_id'].where(s['acquirer_id'].isin(known)),
                     who_sub=prom.map({True: 'promoter group', False: ''}),
                     what=s['regulation'].map(REG_WORDS).fillna('SAST disclosure'), what_sub=sub,
                     side=np.select([act.str.startswith('acq').to_numpy(), act.str.startswith('sale').to_numpy()],
                                    ['BUY', 'SELL'], None),
                     role=prom.map({True: 'Promoter', False: 'Others'}), is_mm=False, also_filed=False)


def _issues(ctx, since, names) -> dict:
    """{source: (built rows, common rows)} for preferential, rights and QIP records."""
    out = {}
    pref = issue_rows(ctx.preferential, ctx.prices)
    rights = rights_rows(ctx.rights, ctx.prices)
    qip = qip_rows(store.table('qip'), ctx.prices)
    for src, rows, what in (('pref', pref, 'Preferential issue'), ('rights', rights, 'Rights issue'), ('qip', qip, 'QIP')):
        if rows.empty:
            continue
        rows = rows[pd.to_datetime(rows['posted_on'], errors='coerce') >= since]
        if rows.empty:
            continue
        cat = _col(rows, 'allottee_category')
        who = {'pref': rows['to'].fillna('') if 'to' in rows else '', 'rights': 'Shareholders',
               'qip': 'Qualified institutions'}[src]
        sub = rows['status'] + (' · ' + rows['ratio'].fillna('') if src == 'rights' and 'ratio' in rows else '')
        out[src] = (rows, _frame(src, rows, group='Capital raises', held=False,
                                 made_public=pd.to_datetime(rows['posted_on'], errors='coerce'),
                                 company=_name(rows, names), nse_symbol=rows['symbol'], isin=rows['isin'],
                                 listed_on='nse', who=who, what=what, what_sub=sub.str.rstrip(' ·'),
                                 value=pd.to_numeric(rows['amount'], errors='coerce'),
                                 role=cat.map({'PROMOTER': 'Promoter', 'NON_PROMOTER': 'Others', 'MIXED': 'Mixed'}),
                                 is_mm=False, also_filed=False))
    return out


def _buybacks(ctx, since, names) -> tuple[pd.DataFrame, pd.DataFrame]:
    r = buybacks.rows(store.table('buybacks'), ctx.prices, ctx.meetings)
    if r.empty:
        return r, pd.DataFrame(columns=COLUMNS)
    r = r[r['when'] >= since]
    if r.empty:
        return r, pd.DataFrame(columns=COLUMNS)
    note = pd.Series(np.where(pd.to_datetime(r['offer_open'], errors='coerce').notna(), 'offer opens',
                              np.where(pd.to_datetime(r['record_date'], errors='coerce').notna(), 'record date',
                                       'first daily report')), index=r.index)
    return r, _frame('buyback', r, group='Corporate actions', held=False, made_public=r['when'], day_note=note,
                     company=_name(r, names), nse_symbol=r['symbol'], isin=r['isin'], listed_on='nse', who='',
                     what='Buyback', what_sub=r['how'].fillna('route not on NSE'),
                     value=pd.to_numeric(r['offer_value'], errors='coerce'), is_mm=False, also_filed=False)


def _actions(ctx, since, names) -> tuple[pd.DataFrame, pd.DataFrame]:
    a = ctx.actions
    if a is None or a.empty:
        return pd.DataFrame(), pd.DataFrame(columns=COLUMNS)
    a = a[a['purpose'].ne('buyback')].copy()   # buybacks are their own rows, with price and route (audit C6)
    seen = pd.to_datetime(_col(a, 'broadcast_date'), errors='coerce')
    ex = pd.to_datetime(a['ex_date'], errors='coerce')
    a['_day'] = seen.fillna(ex)
    a = a[a['_day'] >= since]
    if a.empty:
        return a, pd.DataFrame(columns=COLUMNS)
    note = pd.Series(np.where(pd.to_datetime(_col(a, 'broadcast_date'), errors='coerce').notna(), '', 'ex-date'),
                     index=a.index)
    purpose = a['purpose'].astype(str)
    return a, _frame('action', a, group='Corporate actions', held=False, made_public=a['_day'], day_note=note,
                     company=_name(a, names), nse_symbol=a['symbol'], isin=a['isin'],
                     listed_on=_col(a, 'listed_on', 'nse'), who='',
                     what=purpose.map(ACTION_WORDS).fillna(purpose.str.capitalize()), what_sub=_col(a, 'subject'),
                     is_mm=False, also_filed=False)


def _meeting_detail(desc) -> str:
    """NSE joins every notice of a meeting into one text: keep the short agenda line, not the 'has informed the
    Exchange' boilerplate."""
    parts = [x.strip() for x in _txt(desc).split('|') if x.strip()]
    agenda = [x for x in parts if 'has informed the exchange' not in x.lower()]
    return (agenda or parts or [''])[0][:140]


def _upcoming(ctx, ref, names) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Money events ahead, next UPCOMING_DAYS from the data's as-of day (owner 23 Oct): board meetings that consider
    fund raising, a buyback, a preferential or a rights issue; tender buybacks still open; lock-ins ending."""
    today = pd.Timestamp(ref).normalize()
    end = today + pd.Timedelta(days=UPCOMING_DAYS)
    rows = []
    m = ctx.meetings
    flags = [c for c in MEETING_WORDS if m is not None and c in m]
    if m is not None and not m.empty and 'meeting_date' in m and flags:
        when = pd.to_datetime(m['meeting_date'], errors='coerce')
        hit = m[(when >= today) & (when <= end) & m[flags].astype('boolean').fillna(False).any(axis=1)]
        for r in hit.to_dict('records'):
            said = [MEETING_WORDS[c] for c in flags if pd.notna(r.get(c)) and bool(r.get(c))]
            rows.append(dict(kind='meeting', date=pd.Timestamp(r['meeting_date']), symbol=r.get('symbol'), isin=r.get('isin'),
                             company=r.get('company_display') or r.get('company'), what='Board meets: ' + ', '.join(said),
                             detail=_meeting_detail(r.get('description')), value=None))
    bb = buybacks.rows(store.table('buybacks'), ctx.prices, ctx.meetings)
    if not bb.empty:
        close = pd.to_datetime(bb['offer_close'], errors='coerce')
        for r in bb[(close >= today) & (close <= end)].to_dict('records'):
            rows.append(dict(kind='tender', date=pd.Timestamp(r['offer_close']), symbol=r.get('symbol'), isin=r.get('isin'),
                             company=r.get('company'), what='Buyback tender closes',
                             detail=' · '.join(x for x in (_txt(r.get('how')), f'offer {_price(r.get("offer_price"))}'
                                                           if _num(r.get('offer_price')) is not None else '',
                                                           f'opened {_d(r.get("offer_open"))}' if _d(r.get('offer_open')) else '') if x),
                             value=r.get('offer_value')))
    cal = lock_in_calendar(ctx.preferential, ctx.prices, today, store.table('preferential_lockins'))
    if not cal.empty:
        for r in cal[(cal['expires'] >= today) & (cal['expires'] <= end)].to_dict('records'):
            rows.append(dict(kind='lockin', date=pd.Timestamp(r['expires']), symbol=r.get('symbol'), isin=r.get('isin'),
                             company=r.get('company'), what='Lock-in ends',
                             detail=' · '.join(x for x in (_txt(r.get('what')), f'{_shares(r.get("shares"))} shares'
                                                           if _num(r.get('shares')) is not None else '', _txt(r.get('note'))) if x),
                             value=r.get('at_market')))
    if not rows:
        return pd.DataFrame(), pd.DataFrame(columns=COLUMNS)
    u = pd.DataFrame(rows)
    u['value'] = pd.to_numeric(u['value'], errors='coerce')
    return u, _frame('upcoming', u, group='Upcoming', held=False, made_public=u['date'], company=_name(u, names),
                     nse_symbol=u['symbol'], isin=u['isin'], listed_on='nse', who='', what=u['what'], what_sub=u['detail'],
                     value=u['value'], is_mm=False, also_filed=False)


def build(ctx, days: int) -> tuple[pd.DataFrame, dict]:
    """Every filing made public in the last `days` days to the data's as-of date (forward-dated corporate
    actions included), in the common columns, newest first; and the source rows behind them by `_src`."""
    ref = ctx.ref if ctx.ref is not None else pd.Timestamp.now(tz='Asia/Kolkata').tz_localize(None).normalize()
    since = pd.Timestamp(ref).normalize() - pd.Timedelta(int(days) - 1, unit='D')
    names = _names(ctx)
    known = set(ctx.trades['person_id'].dropna()) if 'person_id' in ctx.trades else set()
    if ctx.deals is not None and 'client_id' in ctx.deals:
        known |= set(ctx.deals['client_id'].dropna())
    parts = {'insider': _insider(ctx, since), 'deal': _deals(ctx, since), 'sast': _sast(ctx, since, names, known),
             **_issues(ctx, since, names), 'buyback': _buybacks(ctx, since, names), 'action': _actions(ctx, since, names),
             'upcoming': _upcoming(ctx, ref, names)}
    # Columns empty in one part are left out of the concat (pandas deprecates letting them set the dtypes).
    frames = [p[1].dropna(axis=1, how='all') for p in parts.values() if not p[1].empty]
    rows = (pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()).reindex(columns=COLUMNS)
    if not rows.empty:
        rows['made_public'] = pd.to_datetime(rows['made_public'], errors='coerce').dt.normalize()
        for c in ('held', 'is_mm', 'also_filed'):
            rows[c] = rows[c].astype('boolean').fillna(False).astype(bool)
        for c in ('who', 'who_sub', 'what_sub', 'day_note'):
            rows[c] = rows[c].map(_txt)
        rows['_v'] = pd.to_numeric(rows['value'], errors='coerce').fillna(-1)
        rows = rows.sort_values(['made_public', '_v'], ascending=False, na_position='last', kind='stable') \
            .drop(columns='_v').reset_index(drop=True)
    return rows, {k: v[0] for k, v in parts.items()}


def in_kind(rows: pd.DataFrame, kind: str) -> pd.Series:
    """Rows under a kind pill. Held-back rows appear only under 'Held back'; 'All' leaves out dividends, deals that
    are an insider's own filed trade (shown under the insider, audit D6) and the money events ahead (their own pill)."""
    held, src, grp = rows['held'], rows['_src'], rows['group']
    if kind == 'Held back':
        return held
    if kind == 'All':
        return ~held & ~rows['also_filed'] & ~(src.eq('action') & rows['what'].eq('Dividend')) & ~grp.eq('Upcoming')
    pick = {'Insider trades': grp.eq('Insider market'), 'Deals': grp.eq('Deals'), 'Stake changes': src.eq('sast'),
            'Preferential': src.eq('pref'), 'Rights': src.eq('rights'), 'QIPs': src.eq('qip'), 'Buybacks': src.eq('buyback'),
            'Pledges': grp.eq('Pledges'), 'Upcoming': grp.eq('Upcoming'),
            'Other filings': grp.eq('Insider other') | src.eq('action')}[kind]
    return ~held & pick


# ---- the facts behind each row ----------------------------------------------------------------

def _insider_facts(x: dict, extra: dict) -> str:
    hb, ha = _num(x.get('holding_before')), _num(x.get('holding_after'))
    change = ''
    if hb is not None and ha is not None:
        dlt = ha - hb
        change = ('+' if dlt > 0 else '') + kit.indian(dlt) + ' shares'
        if _num(x.get('holding_change_pct')) is not None:
            change += f' ({kit.pct(x["holding_change_pct"], 1, signed=True)})'
    f = extra.get('split')
    paid = _num(x.get('price'))
    to_co, to_ex = _num(x.get('insider_to_company_sessions')), _num(x.get('company_to_exchange_sessions'))
    late = late_text(x)
    timing = late or (f'On time (each step within {DISCLOSURE_LIMIT_SESSIONS} sessions)'
                      if to_co is not None and to_ex is not None else '')
    hc, pc = HOLDING_CHECK.get(_txt(x.get('holding_check')), ''), PRICE_CHECK.get(_txt(x.get('price_check')), '')
    items = [
        ('Who', f'{_txt(x.get("person_name"))}, {kit.role(x.get("person_role"))}'),
        ('Category as filed', _txt(x.get('person_category_raw'))),
        ('Shares', _shares(x.get('quantity'))), ('Price as filed', _price(paid)),
        ("Price on today's basis", _price(paid * f) if paid is not None and _num(f) not in (None, 1.0) else ''),
        ('Holding before', _shares(hb)), ('Holding after', _shares(ha)), ('Change in own holding', change),
        ('Traded', _span(x.get('trade_date_from'), x.get('trade_date_to'))),
        ('Told the company', _d(x.get('intimation_date'))
         + (f' · {_after(to_co, "the trade")}' if to_co is not None else '')),
        ('Made public', _d(x.get('broadcast_date'))
         + (f' · {_after(to_ex, "the company was told")}' if to_ex is not None else '')),
        ('Lateness', timing), ('Mode as filed', _txt(x.get('mode_raw'))),
        ('Type as filed', _txt(x.get('transaction_type_raw'))),
        ('Price before public', _pct(extra.get('pre'), True) + ' (last trade day to made public)'
         if _num(extra.get('pre')) is not None else ''),
        ('Now vs paid', _pct(extra.get('vs_paid'), True) if _num(extra.get('vs_paid')) is not None else ''),
        ('Trading window', window_text(x)),
        ('Holding check', hc), ('Price check', pc),
        ('Held back', '; '.join(flag_words(x.get('flags')))), ('Marked', '; '.join(flag_words(x.get('marks')))),
        ('Filed on', _txt(x.get('listed_on')).replace(',', ', ')),
    ]
    url = _txt(x.get('source_url'))
    return facts(items, [('Filing XBRL on NSE' if url.lower().endswith('.xml') else 'Filing', url)] if url else [])


def _deal_facts(x: dict, extra: dict) -> str:
    k = x.get('client_type')
    typ = participants.TYPES.get(k, '') if isinstance(k, str) else ''
    conf = _txt(x.get('client_type_confidence'))
    rule = _txt(x.get('client_type_rule'))
    group = _txt(x.get('investor_group'))
    items = [
        ('Who', _txt(x.get('client_name'))),
        ('Client type', typ + (f' ({conf} confidence' + (f', {rule}' if rule else '') + ')' if conf else '')),
        ('Investor group', group if group and group != _txt(x.get('client_name')) else ''),
        ('Market maker', 'Yes, measured two-way volume' if bool(x.get('client_is_market_maker')) else ''),
        ('Shares', _shares(x.get('quantity'))), ('Price', _price(x.get('price'))),
        ('Trades in the row', _txt(x.get('trades')) if _num(x.get('trades')) not in (None, 1.0) else ''),
        ('Counterparties', _txt(x.get('counterparties'))),
        ('Feed', f'{_txt(x.get("exchange")).upper()} {_txt(x.get("feeds")).replace(",", " and ")} deals of {_d(x.get("date"))}'),
        ('Also an insider filing', 'Yes: the same person, company, side and day' if x.get('_also') else ''),
        ('Held back', '; '.join(flag_words(x.get('flags')))),
        ('Link', 'none per deal: the exchange publishes a daily list'),
    ]
    return facts(items)


def _sast_facts(x: dict, extra: dict) -> str:
    after = _num(x.get('post_stake_pct'))
    traded = _num(x.get('percent_equity_traded'))
    before = after - traded if after is not None and traded is not None else None
    items = [
        ('Who', _txt(x.get('acquirer_name')) + (' (promoter group)' if bool(x.get('is_promoter')) else '')),
        ('Rule', _txt(x.get('regulation'))), ('Action', _txt(x.get('action_type'))), ('Mode as filed', _txt(x.get('mode'))),
        ('Traded', _span(x.get('trade_date_from'), x.get('trade_date_to')) or _d(x.get('transaction_date'))),
        ('Shares acquired', _shares(x.get('shares_acquired'))), ('Shares sold', _shares(x.get('shares_sold'))),
        ('% of capital traded', _pct(traded, True)),
        ('Stake before', _pct(before) + ' (after, less the % traded)' if before is not None else ''),
        ('Stake after', _pct(after)), ('Shares after', _shares(x.get('shares_after'))),
        ('Made public', _txt(x.get('broadcast_ts'))), ('Application no.', _txt(x.get('application_no'))),
        ('Filed on', _txt(x.get('listed_on')).upper()),
    ]
    url = _txt(x.get('attachment'))
    return facts(items, [('Filing on the exchange', url)] if url else [])


def _lock_in(x: dict, lines: pd.DataFrame) -> str:
    if lines is not None and not lines.empty and 'app_id' in lines:
        own = lines[lines['app_id'].astype(str) == _txt(x.get('app_id'))]
        if not own.empty:
            return '; '.join(f'{_shares(s)} shares to {_d(e)}' + (f' ({m:g} months, {b})' if _num(m) is not None else '')
                             for s, e, m, b in zip(own['shares'], own['expires'], own['months'], own['basis']))
    parts = [f'promoters to {_d(x.get("lock_in_promoter_until"))}' if _d(x.get('lock_in_promoter_until')) else '',
             f'others to {_d(x.get("lock_in_other_until"))}' if _d(x.get('lock_in_other_until')) else '']
    return ', '.join(p for p in parts if p) + (' (rule: none filed)' if any(parts) else '')


def _allottees(app_ids, table: pd.DataFrame, share_col: str, pct_col: str | None = None) -> str:
    if table is None or table.empty or 'app_id' not in table:
        return ''
    ids = {str(a) for a in app_ids if _txt(a)}
    own = table[table['app_id'].astype(str).isin(ids)]
    if own.empty:
        return ''
    own = own.sort_values(share_col, ascending=False)
    top = '; '.join(f'{n}' + (f' {kit.pct(p, 2)}' if pct_col and _num(p) is not None else f' {_shares(s)}')
                    for n, s, p in zip(own['allottee'].head(5), own[share_col].head(5),
                                       own[pct_col].head(5) if pct_col else [None] * 5))
    return f'{len(own)} named: {top}' + (f'; and {len(own) - 5} more' if len(own) > 5 else '')


def _issue_facts(src: str, x: dict, extra: dict) -> str:
    approved, raised = _num(x.get('amount_total')), _num(x.get('amount_raised'))
    # Warrants are paid 25% at allotment and 75% on conversion: a listing record of converted warrants raises the
    # 75% balance, not shares x price (30 such records, audit 22 Oct), so the amount says which part it is.
    implied = (_num(x.get('shares_allotted')) or 0) * (_num(x.get('offer_price')) or 0)
    balance = bool(raised and implied and 'warrant' in _txt(x.get('instruments')).lower() and 0.73 <= raised / implied <= 0.77)
    items = [('Stage', _txt(x.get('status'))), ('Board meeting', _d(x.get('board_date'))),
             ('Approved size', _money(approved)),
             ('Raised on conversion (the 75% balance on warrants)' if balance else 'Raised', _money(raised)),
             ('Amount note', 'flagged unreliable by the cleaner' if bool(x.get('amount_unreliable')) else '')]
    if src == 'pref':
        items += [('Shares go to', ALLOTTEE_LABEL.get(_txt(x.get('allottee_category')), '')),
                  ('Instruments', _txt(x.get('instruments'))), ('Consideration', _txt(x.get('consideration'))),
                  ('Offer price', _price(x.get('offer_price'))), ('ICDR minimum, filed', _price(x.get('icdr_min_price'))),
                  ('Offer vs minimum', _pct(x.get('vs_icdr_min'), True)),
                  ('ICDR minimum, our estimate', _price(x.get('icdr_min_ours'))),
                  ('Offer vs market now', _pct(x.get('vs_market'), True)),
                  ('Shares allotted', _shares(x.get('shares_allotted'))), ('Allotted', _d(x.get('allotment_date'))),
                  ('Trading approval', _d(x.get('trading_approval_date'))),
                  ('Lock-in', _lock_in(x, extra.get('lockins'))),
                  ('Allottees', _allottees([x.get('app_id'), x.get('linked_app_id')], extra.get('pref_allottees'),
                                           'securities')),
                  ('Matched', LINK_STATUS.get(_txt(x.get('link_status')), ''))]
    elif src == 'rights':
        items += [('Ratio', _txt(x.get('ratio'))), ('Rights price', _price(x.get('offer_price'))),
                  ('Rights vs market now', _pct(x.get('vs_market'), True)), ('Record date', _d(x.get('record_date'))),
                  ('Issue opens', _d(x.get('issue_open_date'))), ('Issue closes', _d(x.get('issue_close_date'))),
                  ('Shares allotted', _shares(x.get('shares_allotted'))),
                  ('Matched', LINK_STATUS.get(_txt(x.get('link_status')), ''))]
    else:
        items += [('Shareholders approved', _d(x.get('shareholder_approval_date'))),
                  ('Bids', _span(x.get('bid_open_date'), x.get('bid_close_date'))),
                  ('Relevant date', _d(x.get('relevant_date'))), ('Issue price', _price(x.get('issue_price'))),
                  ('Floor price, filed', _price(x.get('floor_price'))),
                  ('Discount per share, filed', _price(x.get('discount_per_share'))),
                  ('Issue vs market now', _pct(x.get('vs_market'), True)),
                  ('Shares allotted', _shares(x.get('shares_allotted'))),
                  ('Allotted', _d(x.get('allotment_date'))), ('Listed at', _txt(x.get('listed_at'))),
                  ('Allottees', _allottees([x.get('app_id')], extra.get('qip_allottees'), 'shares', 'pct_of_issue')
                   or (_txt(x.get('allottees')) if _num(x.get('allottees')) is not None else ''))]
    url = _txt(x.get('xbrl_url'))
    return facts(items, [('Filing XBRL on NSE', url)] if url.startswith('http') else [])


def _buyback_facts(x: dict, extra: dict) -> str:
    return facts([('Route', _txt(x.get('how')) or 'not on NSE'), ('Offer price', _price(x.get('offer_price'))),
                  ('Offer vs market now', _pct(x.get('vs_market'), True)), ('Size', _money(x.get('offer_value'))),
                  ('Shares sought', _shares(x.get('shares_sought'))), ('Shares tendered', _shares(x.get('shares_tendered'))),
                  ('Times tendered', f'{_num(x.get("times_tendered")):.2f}x' if _num(x.get('times_tendered')) is not None else ''),
                  ('Offer', _span(x.get('offer_open'), x.get('offer_close'))), ('Record date', _d(x.get('record_date'))),
                  ('Daily reports', f'{int(x["daily_reports"])}, {_span(x.get("first_report"), x.get("last_report"))}'
                   if _num(x.get('daily_reports')) is not None else ''),
                  ('Source', _txt(x.get('source')))])


def _action_facts(x: dict, extra: dict) -> str:
    fv = (f'₹{_num(x.get("face_value_from")):g} to ₹{_num(x.get("face_value_to")):g}'
          if _num(x.get('face_value_from')) is not None and _num(x.get('face_value_to')) is not None else '')
    return facts([('As filed', _txt(x.get('subject'))), ('Ex-date', _d(x.get('ex_date'))),
                  ('Record date', _d(x.get('record_date'))), ('Ratio', _txt(x.get('ratio'))), ('Face value', fv),
                  ('Rights price', _price(x.get('rights_issue_price'))),
                  ('Dividend per share', _price(x.get('dividend_per_share'))),
                  ('Announced', _d(x.get('broadcast_date'))), ('Listed on', _txt(x.get('listed_on')).upper())])


def _upcoming_facts(x: dict, extra: dict) -> str:
    return facts([('What', _txt(x.get('what'))), ('Date', _d(x.get('date'))), ('Detail', _txt(x.get('detail'))),
                  ('Value', _money(x.get('value')))])


FACTS = {'upcoming': _upcoming_facts, 'insider': _insider_facts, 'deal': _deal_facts, 'sast': _sast_facts, 'buyback': _buyback_facts,
         'action': _action_facts, 'pref': lambda x, e: _issue_facts('pref', x, e),
         'rights': lambda x, e: _issue_facts('rights', x, e), 'qip': lambda x, e: _issue_facts('qip', x, e)}


def _decorate(top: pd.DataFrame, sources: dict, ctx) -> dict:
    """Per shown insider row, what needs prices or the calendar (computed for the shown rows only):
    the move before it was made public, now vs paid for an open-market buy, the split factor; and the
    lateness / trading-window line under What."""
    out = {}
    ins = top[top['_src'] == 'insider']
    if ins.empty:
        return out
    t = sources['insider'].loc[ins['_i']]
    pre = pre_public_move(t)
    split = split_since(t, ctx.prices)
    px = with_prices(t[['isin']], ctx.prices)
    paid = pd.to_numeric(t['price'], errors='coerce') * split
    vs = (pd.to_numeric(px['latest_close'], errors='coerce') / paid - 1) * 100
    buy = _b(t['is_market']) & t['side'].eq('BUY')
    for i in t.index:
        out[i] = {'pre': pre.get(i), 'split': split.get(i), 'vs_paid': vs.get(i) if buy.get(i) else None}
    return out


# ---- one table per kind (docs/DESIGN_V3.md): the extra columns each needs, for the shown rows only ----------

MARKET = (('mk_cap', 'market_cap'), ('mk_px', 'latest_close'), ('mk_lo', 'low_52w'), ('mk_hi', 'high_52w'),
          ('mk_bucket', 'mcap_bucket'))
UNIT_WHY = ('The filed amount fails the unit check (zero, above ₹1 lakh crore, or far from shares × price), '
            'so it is held back rather than shown wrong')


def _market(df: pd.DataFrame, ctx) -> pd.DataFrame:
    """Size bucket, market cap, price and 52-week range for the company cell (from the price summary)."""
    out = df.copy()
    p = ctx.prices
    if p is None or p.empty or 'isin' not in out or 'isin' not in p:
        for new, _ in MARKET:
            out[new] = None
        return out
    q = p.drop_duplicates('isin').set_index('isin')
    for new, old in MARKET:
        out[new] = out['isin'].map(q[old]) if old in q else None
    return out


def _own(top: pd.DataFrame, sources: dict, src: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    """The source rows behind the shown rows of one source, indexed like `top`."""
    mine = top[top['_src'] == src]
    return sources[src].loc[mine['_i']].set_axis(mine.index), mine


def _now_vs(rows: pd.DataFrame, price_col: str, ctx, date_col) -> pd.Series:
    """Price now against a filed price, on today's split basis (audit W9): % ."""
    paid = pd.to_numeric(rows[price_col], errors='coerce') * split_since(rows, ctx.prices, date_col)
    close = pd.to_numeric(with_prices(rows[['isin']], ctx.prices)['latest_close'], errors='coerce')
    return ((close / paid - 1) * 100).where(paid.gt(0) & close.gt(0))


def _k_insider(top, sources, ctx, tables):
    t, _ = _own(top, sources, 'insider')
    out = top.copy()
    out['price'] = pd.to_numeric(t['price'], errors='coerce')
    out['vs_trade'] = _now_vs(t, 'price', ctx, 'trade_date_to')
    out['hold_chg'] = pd.to_numeric(_col(t, 'holding_change_pct'), errors='coerce')
    out['mode'] = _col(t, 'mode_raw').where(_col(t, 'mode_raw').notna(), top['what'])
    out['qty'] = pd.to_numeric(_col(t, 'quantity'), errors='coerce')
    out['hold_after'] = pd.to_numeric(_col(t, 'holding_after'), errors='coerce')
    sess = pd.to_numeric(_col(t, 'trade_to_public_sessions'), errors='coerce')
    out['lag_txt'] = [_after(n, 'the trade') if pd.notna(n) else '' for n in sess]
    # What the row needs a look at, as tags (the sentences are in the row's facts): late filing, window just reopened
    out['flags_txt'] = [','.join(x for x in ('Late' if late_text(r) else '', 'Window open' if window_text(r) else '') if x)
                        for r in t.to_dict('records')]
    return out


def _k_deal(top, sources, ctx, tables):
    d, _ = _own(top, sources, 'deal')
    out = top.copy()
    out['price'] = pd.to_numeric(d['price'], errors='coerce')
    out['vs_trade'] = _now_vs(d, 'price', ctx, 'date')
    out['counter'] = _col(d, 'counterparties').map(lambda v: '; '.join(map(str, v[:3])) if isinstance(v, (list, tuple))
                                                  else _txt(v))
    return out


def _k_sast(top, sources, ctx, tables):
    s_, _ = _own(top, sources, 'sast')
    out = top.copy()
    out['pct_moved'] = pd.to_numeric(_col(s_, 'percent_equity_traded'), errors='coerce')
    out['after'] = pd.to_numeric(_col(s_, 'post_stake_pct'), errors='coerce')
    acq, sold = (pd.to_numeric(_col(s_, c), errors='coerce') for c in ('shares_acquired', 'shares_sold'))
    out['shares_moved'] = acq.where(acq.gt(0), sold)
    out['mode'] = _col(s_, 'mode')
    return out


def _amount_cols(r: pd.DataFrame, out: pd.DataFrame) -> None:
    """The amount, the reason a held-back one is blank, and the line under it."""
    flag = _b(_col(r, 'amount_unreliable', False))
    out['amount'] = pd.to_numeric(_col(r, 'amount'), errors='coerce')
    out['amount_why'] = np.where(flag & out['amount'].isna(), UNIT_WHY, '')
    shares_x_price = pd.to_numeric(_col(r, 'shares_allotted'), errors='coerce') * pd.to_numeric(_col(r, 'offer_price' if 'offer_price' in r else 'issue_price'), errors='coerce')
    approved, raised = (pd.to_numeric(_col(r, c), errors='coerce') for c in ('amount_total', 'amount_raised'))
    sub = []
    for f, a, rz, x in zip(flag & out['amount'].isna(), approved, raised, shares_x_price):
        if f and pd.notna(x):
            sub.append(f'shares × price {kit.rupees(x)}')
        elif pd.notna(a) and pd.notna(rz) and abs(a - rz) > 1:
            sub.append(f'approved {kit.rupees(a)}')
        else:
            sub.append('')
    out['amount_sub'] = sub


def _lock_end(x: dict, lines) -> tuple[str, str]:
    """(dates, basis) of a preferential issue's lock-in: the lines the company filed, else the rule from trading approval."""
    if lines is not None and not lines.empty and 'app_id' in lines:
        own = lines[lines['app_id'].astype(str) == _txt(x.get('app_id'))]
        ends = sorted({pd.Timestamp(e) for e in own['expires'].dropna()}) if not own.empty else []
        if ends:
            return ' · '.join(kit.day(e) for e in ends), 'as filed'
    ends = sorted(t for t in (pd.to_datetime(x.get('lock_in_other_until'), errors='coerce'),
                              pd.to_datetime(x.get('lock_in_promoter_until'), errors='coerce')) if pd.notna(t))
    if not ends:
        return '', ''
    return ' · '.join(kit.day(e) for e in ends), 'rule: others 6 months, promoters 18 months'


def _k_pref(top, sources, ctx, tables):
    r, _ = _own(top, sources, 'pref')
    out = top.copy()
    _amount_cols(r, out)
    for c in ('to', 'instruments', 'status', 'posted_on'):
        out[c] = _col(r, c)
    for c in ('offer_price', 'icdr_min_price', 'vs_icdr_min', 'vs_market'):
        out[c] = pd.to_numeric(_col(r, c), errors='coerce')
    ends = [_lock_end(x, tables.get('lockins')) for x in r.to_dict('records')]
    out['lock_end'], out['lock_sub'] = [e[0] for e in ends], [e[1] for e in ends]
    out['to'] = out['to'].where(out['to'].notna(), 'not matched to its approval')
    return out


def _k_rights(top, sources, ctx, tables):
    r, _ = _own(top, sources, 'rights')
    out = top.copy()
    _amount_cols(r, out)
    for c in ('ratio', 'status'):
        out[c] = _col(r, c)
    for c in ('offer_price', 'vs_market'):
        out[c] = pd.to_numeric(_col(r, c), errors='coerce')
    for c in ('record_date', 'issue_close_date', 'posted_on'):
        out[c] = _col(r, c)
    return out


def _k_qip(top, sources, ctx, tables):
    r, _ = _own(top, sources, 'qip')
    out = top.copy()
    _amount_cols(r, out)
    out['status'] = _col(r, 'status')
    out['posted_on'] = _col(r, 'posted_on')
    for c in ('issue_price', 'floor_price', 'discount_per_share', 'vs_market', 'allottees'):
        out[c] = pd.to_numeric(_col(r, c), errors='coerce')
    return out


def _k_buyback(top, sources, ctx, tables):
    r, _ = _own(top, sources, 'buyback')
    out = top.copy()
    out['route'] = _col(r, 'how').where(_col(r, 'how').notna(), 'route not on NSE')
    out['route_note'] = _col(r, 'note')
    for c in ('offer_price', 'vs_market', 'vs_announce', 'offer_value', 'times_tendered'):
        out[c] = pd.to_numeric(_col(r, c), errors='coerce')
    for c in ('offer_open', 'offer_close'):
        out[c] = _col(r, c)
    return out


KIND_SPECS = {
    'Insider trades': (_k_insider, [
        kit.Col('company', 'Company', 'co2'),
        kit.Col('who', 'Who', 'client', sub='who_sub'),
        kit.Col('side', 'Side', 'side'),
        kit.Col('value', 'Value', 'money'),
        kit.Col('pct_of_mcap', '% of mcap', 'bar'),
        kit.Col('price', 'Price', 'price', phone=False),
        kit.Col('vs_trade', 'Price now vs trade', 'vspct', help='Today\'s price against the price in the filing, on today\'s split basis. '
                'Coloured for a buy only: after a sale a rise is neither good nor bad news'),
        kit.Col('hold_chg', 'Own holding Δ', 'spct', phone=False, help="Change in the person's own holding"),
        kit.Col('made_public', 'Made public', 'date', sub='lag_txt'),
        kit.Col('mode', 'Mode as filed', phone=False),
        kit.Col('flags_txt', 'Flags', 'tags', phone=False, help='Late: filed after the 2-trading-day limit. Window open: a buy in the '
                'first sessions after the trading window reopened. The sentences are in the row')]),
    'Deals': (_k_deal, [
        kit.Col('company', 'Company', 'co2'),
        kit.Col('who', 'Client', 'client', sub='who_sub'),
        kit.Col('side', 'Side', 'side'),
        kit.Col('value', 'Value', 'money'),
        kit.Col('pct_of_mcap', '% of mcap', 'bar'),
        kit.Col('price', 'Price', 'price', phone=False),
        kit.Col('vs_trade', 'Price now vs deal', 'vspct', phone=False),
        kit.Col('what', 'Deal', sub='what_sub', phone=False),
        kit.Col('counter', 'Other side', phone=False, wrap=True),
        kit.Col('made_public', 'Date', 'date')]),
    'Stake changes': (_k_sast, [
        kit.Col('company', 'Company', 'co2'),
        kit.Col('who', 'Who', 'client', sub='who_sub'),
        kit.Col('side', 'Side', 'side'),
        kit.Col('pct_moved', '% of company moved', 'spct', help='Of the share capital, as filed'),
        kit.Col('after', 'Stake after', 'pct'),
        kit.Col('shares_moved', 'Shares', 'shares', phone=False),
        kit.Col('mode', 'Mode', phone=False),
        kit.Col('made_public', 'Made public', 'date', sub='what')]),
    'Preferential': (_k_pref, [
        kit.Col('made_public', 'Posted', 'date', sub='status'),
        kit.Col('company', 'Company', 'co2'),
        kit.Col('to', 'Shares go to', sub='instruments', wrap=True),
        kit.Col('amount', 'Amount', 'amt', flag='amount_why', sub='amount_sub',
                help='What was raised once allotted, else the approved size'),
        kit.Col('offer_price', 'Offer price', 'price', phone=False),
        kit.Col('icdr_min_price', 'ICDR minimum', 'price', phone=False, help='The minimum issue price under SEBI ICDR, as the company filed it'),
        kit.Col('vs_icdr_min', 'Offer vs minimum', 'npct', phone=False),
        kit.Col('vs_market', 'Offer vs now', 'npct', phone=False, help='Negative: the shares were offered below today\'s price'),
        kit.Col('lock_end', 'Lock-in ends', 'text', sub='lock_sub', wrap=True)]),
    'Rights': (_k_rights, [
        kit.Col('made_public', 'Posted', 'date', sub='status'),
        kit.Col('company', 'Company', 'co2'),
        kit.Col('ratio', 'Ratio'),
        kit.Col('offer_price', 'Rights price', 'price'),
        kit.Col('vs_market', 'Rights vs now', 'npct', phone=False),
        kit.Col('record_date', 'Record date', 'date', phone=False),
        kit.Col('issue_close_date', 'Closes', 'date', phone=False),
        kit.Col('amount', 'Amount', 'amt', flag='amount_why', sub='amount_sub')]),
    'QIPs': (_k_qip, [
        kit.Col('made_public', 'Posted', 'date', sub='status'),
        kit.Col('company', 'Company', 'co2'),
        kit.Col('allottees', 'Allottees', 'num', phone=False),
        kit.Col('amount', 'Amount', 'amt', flag='amount_why', sub='amount_sub'),
        kit.Col('issue_price', 'Issue price', 'price'),
        kit.Col('floor_price', 'Floor price', 'price', phone=False),
        kit.Col('discount_per_share', 'Discount per share', 'price', phone=False),
        kit.Col('vs_market', 'Issue vs now', 'npct', phone=False)]),
    'Buybacks': (_k_buyback, [
        kit.Col('made_public', 'Starts', 'date', sub='day_note'),
        kit.Col('company', 'Company', 'co2'),
        kit.Col('route', 'Route', sub='route_note', wrap=True),
        kit.Col('offer_price', 'Offer price', 'price'),
        kit.Col('vs_market', 'Offer vs now', 'npct', phone=False, help='Positive: the company offers more than today\'s price'),
        kit.Col('vs_announce', 'Offer vs before the board meeting', 'npct', phone=False),
        kit.Col('value', 'Size', 'money', phone=False),
        kit.Col('times_tendered', 'Tendered ×', 'num', phone=False),
        kit.Col('offer_close', 'Closes', 'date', phone=False)]),
    'Pledges': (_k_insider, [
        kit.Col('made_public', 'Made public', 'date', sub='lag_txt'),
        kit.Col('company', 'Company', 'co2'),
        kit.Col('who', 'Promoter or insider', 'client', sub='who_sub'),
        kit.Col('what', 'Event', sub='what_sub', wrap=True),
        kit.Col('qty', 'Shares', 'shares'),
        kit.Col('value', 'Value', 'money', phone=False),
        kit.Col('pct_of_mcap', '% of mcap', 'bar', phone=False),
        kit.Col('hold_after', 'Holding after', 'shares', phone=False),
        kit.Col('mode', 'Mode as filed', phone=False)]),
    'Upcoming': (lambda top, sources, ctx, tables: top, [
        kit.Col('made_public', 'Date', 'date'),
        kit.Col('company', 'Company', 'co2'),
        kit.Col('what', 'What', wrap=True),
        kit.Col('what_sub', 'Detail', wrap=True, phone=False),
        kit.Col('value', 'Size', 'money', phone=False)]),
}
GENERIC_COLS = [
    kit.Col('company', 'Company', 'co2'),
    kit.Col('who', 'Who', 'client', sub='who_sub'),
    kit.Col('what', 'What', sub='what_sub'),
    kit.Col('side', 'Side', 'side'),
    kit.Col('value', 'Value', 'money', help='Insider and deal value as filed; for an issue the amount raised once '
                                            'allotted, else the approved size; for a buyback its size'),
    kit.Col('pct_of_mcap', '% of mcap', 'bar', phone=False),
    kit.Col('made_public', 'Made public', 'date', sub='day_note'),
]


# ---- the page -------------------------------------------------------------------------------------

def render():
    ctx = load()
    if not need_data(ctx):
        kit.head('Filings', 'Every filing and deal in one place.')
        return
    kit.head('Filings', f'Every filing and deal, one kind at a time, each with its own columns · '
                        f'insider filings to {kit.day(ctx.ref)}')
    kind_slot = st.container()
    # One bar (22 Oct, as the owner's screener): search and period in sight, the rest in "Filters & sort",
    # so a phone shows filings on its first screen, not four rows of filters.
    with st.container(key='fa_filters', horizontal=True, vertical_alignment='center', gap='small'):
        q = st.text_input('Search', placeholder='Company, symbol or name', key='fa_q', type='search',
                          label_visibility='collapsed', width=260)
        days = st.segmented_control('Period', list(PERIODS), default=30, format_func=PERIODS.get, required=True,
                                    key='fa_days', label_visibility='collapsed') or 30
        with st.popover('Filters & sort', icon=':material/tune:', width='content'):
            side = st.segmented_control('Side', ['Buy and sell', 'Buy', 'Sell'], default='Buy and sell', required=True,
                                        key='fa_side') or 'Buy and sell'
            roles = st.pills('Who', ROLES, selection_mode='multi', key='fa_roles')
            floor = st.selectbox('Smallest value', list(MIN_VALUE), format_func=MIN_VALUE.get, key='fa_min')
            mm = st.toggle('Market makers', value=False, key='fa_mm',
                           help='Bulk/block clients measured buying and selling in equal measure; left out unless on')
            money = st.toggle('Real money only', value=False, key='fa_money',
                              help="Today's gates applied to single rows: a decision-maker's open-market trade of ₹25 L and 0.05% "
                                   'of the company (0.25% alone, or ₹25 Cr), a director or KMP selling only at ₹25 Cr, deals of '
                                   '₹25 Cr or 0.25%, stake changes except lenders, issues of ₹100 Cr or more, all buybacks. '
                                   'Pledges, dividends, other filings and dates ahead are left out')

    rows, sources = build(ctx, int(days))
    if not rows.empty:
        if not mm:
            rows = rows[~rows['is_mm']]
        if side != 'Buy and sell':
            rows = rows[rows['side'].eq(side.upper())]
        if roles:
            rows = rows[rows['role'].isin(roles) | (rows['role'].eq('Mixed') & bool({'Promoter', 'Others'} & set(roles)))]
        if q:
            hit = lambda c: rows[c].astype(str).str.contains(q, case=False, na=False, regex=False)  # noqa: E731
            rows = rows[hit('company') | hit('nse_symbol') | hit('who')]
        if floor:
            rows = rows[pd.to_numeric(rows['value'], errors='coerce') >= floor]
    left_out = 0
    if money and not rows.empty:
        keep = filings_rules.real_money(rows)
        left_out = int((~keep & in_kind(rows, 'All')).sum())
        rows = rows[keep].reset_index(drop=True)
    counts = {k: int(in_kind(rows, k).sum()) if not rows.empty else 0 for k in KINDS}
    with kind_slot:
        kind = st.pills('Kind', KINDS, default='All', key='fa_kind', label_visibility='collapsed',
                        format_func=lambda k: f'{k} · {kit.indian(counts.get(k, 0))}') or 'All'
    shown = rows[in_kind(rows, kind)] if not rows.empty else rows
    if kind == 'Upcoming' and not shown.empty:   # what is next first
        shown = shown.sort_values('made_public', kind='stable')
    if shown.empty:
        kit.empty('No filings for these filters.')
        return

    if left_out:
        kit.caption(f'Real money only: {kit.count(left_out)} filings left out (pledges, dividends, small trades and other filings).')
    top = shown.head(LIMIT).copy()
    extra = _decorate(top, sources, ctx)
    ins = top['_src'] == 'insider'
    if ins.any():
        src = sources['insider']
        top.loc[ins, 'what_sub'] = [late_text(r) or window_text(r) for r in src.loc[top.loc[ins, '_i']].to_dict('records')]
    held = top['held']
    if held.any():
        top.loc[held, 'what_sub'] = ['; '.join(flag_words(sources[s].loc[i].get('flags'))).capitalize()
                                     for s, i in zip(top.loc[held, '_src'], top.loc[held, '_i'])]
    top = with_flags(_market(top, ctx))
    tables = {'lockins': store.table('preferential_lockins'), 'pref_allottees': store.table('preferential_allottees'),
              'qip_allottees': store.table('qip_allottees')}
    spec = KIND_SPECS.get(kind)
    if spec:
        top = spec[0](top, sources, ctx, tables)
    shown = pd.concat([top, shown.iloc[LIMIT:]], ignore_index=True) if len(shown) > LIMIT else top

    def detail(r: dict) -> str:
        src, i = r.get('_src'), r.get('_i')
        frame = sources.get(src)
        if frame is None or i not in frame.index:
            return ''
        own = extra.get(i, {}) if src == 'insider' else {}
        return f'<p class="hl">{kit.esc(filings_rules.headline(r))}</p>' + FACTS[src](frame.loc[i].to_dict(), {**own, **tables})

    kit.table(shown, spec[1] if spec else GENERIC_COLS, limit=LIMIT, height=760, detail=detail, key=f'fa_{kind}',
              keep_empty=bool(spec))
