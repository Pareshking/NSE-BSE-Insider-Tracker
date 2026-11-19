"""Public shareholders over 1%: who they are, in each company and quarter, and what changed since the company's
previous quarter (docs/DATA_DICTIONARY.md, public_holders).

The shareholding pattern names every public shareholder holding more than 1% (Tables III and IV;
collectors/nse_events, parsers.parse_shp_public_holders). The rows are kept as filed; `holder_key` is the one
spelling used to follow a holder across companies and quarters. It only removes spelling and corporate-suffix
variants ("SBI Mutual Funds", "SBI MUTUAL FUND", "Sbi Mutual Fund." are one key); words that name a different
account stay ("Nippon Life India Trustee Ltd-A/C Nippon India Etf Nifty 50 Bees" is not "Nippon Life India
Trustee"). Nothing is matched by similarity.

Pure functions, no I/O.
"""
from __future__ import annotations

import html
import re

import pandas as pd

from .entities import entity_display

HOLDER_COLUMNS = ['event_id', 'record_id', 'symbol', 'isin', 'company', 'quarter_end', 'submission_date',
                  'holder_no', 'holder_name_filed', 'holder_name', 'holder_key', 'type', 'category', 'section',
                  'sub_category', 'shares', 'pct_of_company', 'holders_check', 'xbrl_url', 'xbrl_sha256', 'parsed_on']
# The investor types, in words (the `{type}` names of docs/DATA_DICTIONARY.md, shareholding)
TYPE_LABELS = {'mf': 'Mutual fund', 'insurance': 'Insurer', 'banks_fi': 'Bank or financial institution',
               'aif': 'AIF', 'other_dii': 'Pension fund or other domestic institution', 'fpi': 'Foreign portfolio investor',
               'other_foreign': 'Foreign direct or other foreign institution', 'govt': 'Government',
               'hni': 'Individual over ₹2 lakh', 'corporate': 'Body corporate', 'other_public': 'Other public'}
CHANGE_COLUMNS = ['isin', 'symbol', 'holder_key', 'holder_name', 'type', 'quarter_end', 'prev_quarter_end',
                  'shares', 'prev_shares', 'pct_of_company', 'prev_pct', 'change', 'shares_change', 'pct_change']

_SUFFIX = {'ltd', 'limited', 'pvt', 'private'}
_WORDS = {'co': 'company', 'corp': 'corporation', 'funds': 'fund', 'intl': 'international'}


def holder_key(name) -> str | None:
    """Lower case, punctuation out, `&` as `and`, Ltd / Limited / Pvt / Private and a leading "The" dropped, a few
    abbreviations and plurals spelled one way (Co, Corp, Intl, Funds); "A/c", "A/C." written `ac` and kept with what
    follows it, so each account stays its own holder. Words joined by '-', as entity_key, so a key is also an
    /entity id."""
    if name is None or (isinstance(name, float) and pd.isna(name)):
        return None
    s = html.unescape(str(name)).lower().replace('&', ' and ')
    s = re.sub(r'\ba\s*/\s*c\b\.?', ' ac ', s)
    words = [_WORDS.get(w, w) for w in re.sub(r'[^a-z0-9]+', ' ', s).split()]
    words = [w for w in words if w not in _SUFFIX]
    if words[:1] == ['the']:
        words = words[1:]
    return '-'.join(words) or None


def holder_rows(holders: list[dict], filing: dict, check: str, sha: str | None, run_date: str) -> pd.DataFrame:
    """Parsed holders of one filing -> rows with the filing's identity (as promoter_group.member_rows)."""
    from .promoter_group import _identity
    rows = [{**_identity(filing), **h, 'holder_name': entity_display(h['holder_name_filed']),
             'holder_key': holder_key(h['holder_name_filed']), 'holders_check': check,
             'xbrl_sha256': sha, 'parsed_on': run_date} for h in holders]
    return pd.DataFrame(rows, columns=HOLDER_COLUMNS)


def clean_holders(batches: list[pd.DataFrame]) -> tuple[pd.DataFrame, dict]:
    """Write-once parse batches -> one holder list per company and quarter. A filing parsed twice keeps its latest
    parse; a revised filing for the same quarter replaces the original (latest submission)."""
    frames = [b for b in batches if b is not None and not b.empty]
    if not frames:
        return pd.DataFrame(columns=HOLDER_COLUMNS), {'filings': 0, 'holders': 0, 'companies': 0}
    df = pd.concat(frames, ignore_index=True)
    df['quarter_end'] = pd.to_datetime(df['quarter_end'], errors='coerce')
    df['submission_date'] = pd.to_datetime(df['submission_date'], errors='coerce')
    df = df[df['parsed_on'] == df.groupby('event_id')['parsed_on'].transform('max')]
    pick = (df.drop_duplicates('event_id').sort_values(['symbol', 'quarter_end', 'submission_date', 'event_id'])
              .drop_duplicates(['symbol', 'quarter_end'], keep='last')['event_id'])
    df = df[df['event_id'].isin(set(pick))].drop_duplicates(['event_id', 'holder_no'], keep='last')
    df = df.sort_values(['symbol', 'quarter_end', 'holder_no']).reset_index(drop=True)
    for c in ('shares', 'pct_of_company'):
        df[c] = pd.to_numeric(df[c], errors='coerce')
    filings = df.drop_duplicates('event_id')
    rep = {'filings': int(len(filings)), 'holders': int(len(df)), 'companies': int(df['symbol'].nunique()),
           'holder_keys': int(df['holder_key'].nunique()),
           'by_type': {str(k): int(v) for k, v in df['type'].value_counts().items()},
           'holders_check': {str(k): int(v) for k, v in filings['holders_check'].value_counts().items()},
           'quarters': {k.strftime('%Y-%m-%d'): int(v) for k, v in
                        filings['quarter_end'].value_counts().sort_index(ascending=False).head(4).items()}}
    return df[HOLDER_COLUMNS], rep


def changes(holders: pd.DataFrame) -> pd.DataFrame:
    """Each company's latest quarter against its previous one, per holder_key: `new` (named now, not in the previous
    list: crossed 1%), `exited` (named before, not now: under 1% or sold out; the filing does not say which),
    `added`, `cut`, `same`; `no_previous` when the company has only one quarter here (nothing to compare, not new).
    shares_change in shares, pct_change in points of the company (an exited holder's now is blank, the change is
    then minus the previous holding). One holder_key named twice in a list (two schemes filed under one name) is
    summed."""
    if holders is None or holders.empty:
        return pd.DataFrame(columns=CHANGE_COLUMNS)
    h = holders.dropna(subset=['isin', 'holder_key', 'quarter_end']).copy()
    h['quarter_end'] = pd.to_datetime(h['quarter_end'], errors='coerce')
    qs = h.drop_duplicates(['isin', 'quarter_end'])[['isin', 'quarter_end']].sort_values(['isin', 'quarter_end'])
    qs['rank'] = qs.groupby('isin').cumcount(ascending=False)
    last = qs[qs['rank'] == 0].set_index('isin')['quarter_end']
    prev = qs[qs['rank'] == 1].set_index('isin')['quarter_end']
    agg = (h.groupby(['isin', 'quarter_end', 'holder_key'], as_index=False)
             .agg(symbol=('symbol', 'first'), holder_name=('holder_name', 'first'), type=('type', 'first'),
                  shares=('shares', 'sum'), pct_of_company=('pct_of_company', 'sum')))
    now = agg[agg['quarter_end'].eq(agg['isin'].map(last))]
    before = agg[agg['quarter_end'].eq(agg['isin'].map(prev))]
    out = now.merge(before[['isin', 'holder_key', 'holder_name', 'type', 'symbol', 'shares', 'pct_of_company']]
                    .rename(columns={'shares': 'prev_shares', 'pct_of_company': 'prev_pct', 'holder_name': 'prev_name',
                                     'type': 'prev_type', 'symbol': 'prev_symbol'}),
                    on=['isin', 'holder_key'], how='outer')
    out['quarter_end'] = out['isin'].map(last)
    out['prev_quarter_end'] = out['isin'].map(prev)
    for c, p in (('holder_name', 'prev_name'), ('type', 'prev_type'), ('symbol', 'prev_symbol')):
        out[c] = out[c].where(out[c].notna(), out[p])
    has_now, has_prev = out['shares'].notna(), out['prev_shares'].notna()
    s, ps = out['shares'].fillna(0.0), out['prev_shares'].fillna(0.0)
    out['change'] = 'same'
    out.loc[has_now & has_prev & (s > ps), 'change'] = 'added'
    out.loc[has_now & has_prev & (s < ps), 'change'] = 'cut'
    out.loc[has_now & ~has_prev, 'change'] = 'new'
    out.loc[~has_now & has_prev, 'change'] = 'exited'
    out.loc[out['prev_quarter_end'].isna(), 'change'] = 'no_previous'
    out['shares_change'] = (s - ps).where(out['prev_quarter_end'].notna())
    out['pct_change'] = (out['pct_of_company'].fillna(0.0) - out['prev_pct'].fillna(0.0)).round(4) \
        .where(out['prev_quarter_end'].notna())
    # largest holding first, the holders that left the list after them
    out = out.assign(_o=out['change'].eq('exited'), _p=out['pct_of_company'].fillna(out['prev_pct']))
    return out.sort_values(['isin', '_o', '_p'], ascending=[True, True, False])[CHANGE_COLUMNS].reset_index(drop=True)


def holdings_of(holders: pd.DataFrame, keys) -> pd.DataFrame:
    """Every company where one of `keys` is named at the company's latest quarter here, with the change since the
    company's previous quarter (`changes`), largest share of the company first."""
    keys = {k for k in keys if k}
    if holders is None or holders.empty or not keys:
        return pd.DataFrame(columns=CHANGE_COLUMNS)
    isins = set(holders.loc[holders['holder_key'].isin(keys), 'isin'].dropna())
    ch = changes(holders[holders['isin'].isin(isins)])
    ch = ch[ch['holder_key'].isin(keys) & ch['change'].ne('exited')]
    return ch.sort_values('pct_of_company', ascending=False).reset_index(drop=True)
