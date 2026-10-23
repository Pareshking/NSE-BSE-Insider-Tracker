"""Filings: the "Real money only" switch and the one-line headline of a row (design V3, owner 23 Oct).

Both read the common columns of `filings_all.build` only. "Real money only" applies Today's gates (insiders_clean/ideas.py)
to single rows: Today nets a decision-maker's trades over the period and counts buying days, which one row cannot; so a row
that is a small part of a larger decision can pass on Today and fail here, never the other way for the thresholds. The page
says how many filings it left out."""
from __future__ import annotations

import pandas as pd
from ui import kit

from insiders_clean import ideas

SELL_ROLES_AT_BIG_ONLY = ('Director/KMP',)
VERBS = {'BUY': 'bought', 'SELL': 'sold'}


def _num(s: pd.Series) -> pd.Series:
    return pd.to_numeric(s, errors='coerce')


def real_money(rows: pd.DataFrame) -> pd.Series:
    """True for the rows that move real money. Insider market trades: a promoter's or promoter group's at Rs 25 lakh and 0.05%
    of the company, or 0.25% alone, a director's or KMP's buy likewise, a director's or KMP's sale only at Rs 25 crore, and any
    decision-maker at Rs 25 crore; employees and other insiders never. Deals: one client's leg of Rs 25 crore or 0.25% of the
    company, market makers and an insider's own filed trade out. Stake changes (SAST): all but a lender's trustee or agent.
    Issues: Rs 100 crore or more (the share count behind Today's 2% dilution gate is not on a row). Buybacks: all.
    Pledges, other insider filings, corporate actions and meetings ahead: out."""
    if rows.empty:
        return pd.Series(dtype=bool)
    v, p = _num(rows['value']), _num(rows['pct_of_mcap']).abs()
    role, side, src, grp = rows['role'], rows['side'], rows['_src'], rows['group']
    floors = (v >= ideas.MIN_VALUE) & (p >= ideas.MIN_PCT) | (p >= ideas.ALONE_PCT)
    big = v >= ideas.BIG_VALUE
    decision = role.isin(['Promoter', 'Director/KMP'])
    insider = grp.eq('Insider market') & decision & (
        side.eq('BUY') & (floors | big)
        | side.eq('SELL') & ((role.eq('Promoter') & (floors | big)) | (role.isin(SELL_ROLES_AT_BIG_ONLY) & big)))
    deal = grp.eq('Deals') & ~rows['is_mm'] & ~rows['also_filed'] & (big | (p >= ideas.FUND_NET_PCT))
    lender = rows['who'].astype(str).str.contains(ideas.SECURITY_HOLDER)
    sast = src.eq('sast') & ~lender
    issue = src.isin(['pref', 'rights', 'qip']) & (v >= ideas.RAISE_MIN_AMOUNT)
    return (insider | deal | sast | issue | src.eq('buyback')).fillna(False).astype(bool)


def _low(text: str) -> str:
    """'Bulk deal' -> 'bulk deal', but 'QIP' and 'SAST disclosure' keep their capitals."""
    return text if text[:2].isupper() else text[:1].lower() + text[1:]


def headline(r: dict) -> str:
    """One sentence for a row, from its own fields (never a model); a figure the row lacks is left out, never guessed."""
    t = lambda k: str(r.get(k) or '').strip() if not (isinstance(r.get(k), float) and pd.isna(r.get(k))) else ''   # noqa: E731
    who, sub, what, note, company = t('who'), t('who_sub'), t('what'), t('what_sub'), t('company')
    val, pct = kit._finite(r.get('value')), kit._finite(r.get('pct_of_mcap'))
    amount = f' {kit.rupees(val)}' if val is not None else ''
    share = f', {kit.pct(abs(pct), 2 if abs(pct) >= 0.1 else 3)} of the company' if pct is not None else ''
    verb = VERBS.get(r.get('side'))
    src, grp = r.get('_src'), r.get('group')
    who_sub = f'{who} ({sub})' if who and sub else who
    if grp == 'Insider market' and verb and who:
        return f'{who_sub} {verb}{amount} of {company or "the company"}{share}, on the open market.'
    if grp == 'Deals' and verb and who:
        return f'{who_sub} {verb}{amount} of {company or "the company"}{share}, in a {_low(what) or "bulk or block deal"}.'
    if src == 'sast' and who:
        return f'{who_sub} filed a stake change in {company or "the company"}: {_low(what)}{", " + note if note else ""}.'
    if src in ('pref', 'rights', 'qip'):
        return f'{company or "The company"}: {_low(what)}{" of" + amount if amount else ""}{", " + note if note else ""}.'
    if src == 'buyback':
        return f'{company or "The company"}: buyback{" of" + amount if amount else ""}{", " + note if note else ""}.'
    if who:
        return f'{who_sub}: {_low(what) or "filing"}{amount}{", " + note if note else ""}.'
    return f'{company or "The company"}: {_low(what) or "filing"}{", " + note if note else ""}.'
