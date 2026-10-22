"""Promoter group: who belongs to it (from the shareholding pattern) and which
insider filings are by one of its members (docs/TODO.md item 21).

The quarterly shareholding pattern names every promoter and promoter-group
member (collectors/nse_events, parsers.parse_shp_members). A filing is linked
to its company's promoter group only by identity: the filer's `person_id`
(insiders_clean.entities.entity_key of the name) equals a member's key in that
company's latest member list. One more exact key is tried on either side:
the name before a bracket, because the pattern names a HUF or a trust with
its karta or trustees in brackets ("VAKIL HUF (VARUN AMAR VAKIL)", "ACC AP
TRUST (Urvashi ...)") and a filer may add a former name ("IRB Holding Private
Limited (Formerly known as Mhaiskar Ventures Private Limited)"). Nothing is
matched by similarity: a filer whose key is not in the list stays unlinked
("JSL Overseas Holding LTF" for "... LTD" stays unlinked).

The member list is the latest quarter we have, applied to every filing of the
company in the window. Membership rarely changes between quarters, but a list
published after a filing is, strictly, later information; named in
docs/SIGNALS.md.

Pure functions, no I/O.
"""
from __future__ import annotations

import pandas as pd

from .entities import entity_display, entity_key

MEMBER_COLUMNS = ['event_id', 'record_id', 'symbol', 'isin', 'company', 'quarter_end', 'submission_date',
                  'member_no', 'member_id', 'member_alt_id', 'member_name', 'member_name_filed', 'section',
                  'sub_category', 'shares', 'pct_of_company', 'pledged_shares', 'members_check',
                  'xbrl_url', 'xbrl_sha256', 'parsed_on']
DECISION_ROLES = ('promoter', 'promoter_group', 'director', 'kmp')
PROMOTER_ROLES = ('promoter', 'promoter_group')


def alt_key(name) -> str | None:
    """The key of the name before its first bracket, when that differs."""
    s = str(name or '')
    if '(' not in s:
        return None
    k = entity_key(s.split('(', 1)[0])
    return k if k and k != entity_key(s) else None


def member_rows(members: list[dict], filing: dict, check: str, sha: str | None, run_date: str) -> pd.DataFrame:
    """Parsed members of one filing -> rows with the filing's identity."""
    rows = [{**{k: filing.get(k) for k in ('event_id', 'record_id', 'symbol', 'isin', 'company', 'quarter_end',
                                            'submission_date', 'xbrl_url')},
             **m, 'member_id': entity_key(m['member_name_filed']), 'member_alt_id': alt_key(m['member_name_filed']),
             'member_name': entity_display(m['member_name_filed']), 'members_check': check,
             'xbrl_sha256': sha, 'parsed_on': run_date} for m in members]
    return pd.DataFrame(rows, columns=MEMBER_COLUMNS)


def clean_members(batches: list[pd.DataFrame]) -> tuple[pd.DataFrame, dict]:
    """Write-once parse batches -> one member list per company and quarter.
    A filing parsed twice keeps its latest parse; a revised filing for the
    same quarter replaces the original (latest submission)."""
    frames = [b for b in batches if b is not None and not b.empty]
    if not frames:
        return pd.DataFrame(columns=MEMBER_COLUMNS), {'filings': 0, 'members': 0, 'companies': 0}
    df = pd.concat(frames, ignore_index=True)
    df['quarter_end'] = pd.to_datetime(df['quarter_end'], errors='coerce')
    df['submission_date'] = pd.to_datetime(df['submission_date'], errors='coerce')
    last_parse = df.groupby('event_id')['parsed_on'].transform('max')
    df = df[df['parsed_on'] == last_parse]
    pick = (df.drop_duplicates('event_id').sort_values(['symbol', 'quarter_end', 'submission_date', 'event_id'])
              .drop_duplicates(['symbol', 'quarter_end'], keep='last')['event_id'])
    df = df[df['event_id'].isin(set(pick))].drop_duplicates(['event_id', 'member_no'], keep='last')
    df = df.sort_values(['symbol', 'quarter_end', 'member_no']).reset_index(drop=True)
    for c in ('shares', 'pct_of_company', 'pledged_shares'):
        df[c] = pd.to_numeric(df[c], errors='coerce')
    filings = df.drop_duplicates('event_id')
    latest = filings.sort_values('quarter_end').drop_duplicates('symbol', keep='last')
    rep = {
        'filings': int(len(filings)), 'members': int(len(df)), 'companies': int(df['symbol'].nunique()),
        'latest_quarter_of_company': {k.strftime('%Y-%m-%d'): int(v) for k, v in
                                      latest['quarter_end'].value_counts().sort_index(ascending=False).head(4).items()},
        'members_check': {str(k): int(v) for k, v in filings['members_check'].value_counts().items()},
        'by_sub_category': {str(k): int(v) for k, v in df['sub_category'].value_counts().head(12).items()},
    }
    return df[MEMBER_COLUMNS], rep


def latest_lists(group: pd.DataFrame | None) -> pd.DataFrame:
    """Each company's latest member list, keyed by ISIN (a filing whose ISIN
    could not be placed links nothing)."""
    if group is None or group.empty:
        return pd.DataFrame(columns=['co', 'member_id', 'member_alt_id', 'quarter_end'])
    g = group.dropna(subset=['isin']).copy()
    g['quarter_end'] = pd.to_datetime(g['quarter_end'], errors='coerce')
    g['co'] = g['isin'].astype(str)
    latest = g.groupby('co')['quarter_end'].transform('max')
    return g[g['quarter_end'] == latest][['co', 'member_id', 'member_alt_id', 'quarter_end']]


def link(trades: pd.DataFrame, group: pd.DataFrame | None) -> tuple[pd.DataFrame, dict]:
    """Adds `promoter_group_id` ('group:<ISIN>' when the filer is a member of
    that company's latest promoter-group list, else blank),
    `promoter_group_quarter` (the list's quarter) and `promoter_group_key`
    ('name' or 'name_before_bracket'). Returns (trades, counts)."""
    t = trades.copy()
    for c in ('promoter_group_id', 'promoter_group_quarter', 'promoter_group_key'):
        t[c] = None
    lists = latest_lists(group)
    if t.empty or lists.empty:
        return t, {'lists': 0, 'note': 'no promoter-group lists yet' if lists.empty else 'no filings'}
    has = set(lists['co'])
    quarter = lists.groupby('co')['quarter_end'].max()
    exact = set(zip(lists['co'], lists['member_id']))
    alt = set(zip(lists['co'], lists['member_alt_id'].dropna()))
    co = t['isin']
    pairs = list(zip(co, t['person_id']))
    filer_alt = list(zip(co, t['person_name'].map(alt_key) if 'person_name' in t else [None] * len(t)))
    by_name = pd.Series([p in exact for p in pairs], index=t.index)
    by_alt = pd.Series([p in alt or (f[1] is not None and (f in exact or f in alt)) for p, f in zip(pairs, filer_alt)],
                       index=t.index) & ~by_name
    hit = by_name | by_alt
    t.loc[hit, 'promoter_group_id'] = 'group:' + co[hit].astype(str)
    t.loc[hit, 'promoter_group_quarter'] = co[hit].map(quarter).dt.strftime('%Y-%m-%d')
    t.loc[by_name, 'promoter_group_key'] = 'name'
    t.loc[by_alt, 'promoter_group_key'] = 'name_before_bracket'
    listed = co.isin(has)
    rep = {'lists': int(len(has))}
    for label, roles in (('promoter_filings', PROMOTER_ROLES), ('director_kmp_filings', ('director', 'kmp'))):
        m = t['person_role'].isin(roles)
        rep[label] = {'all': int(m.sum()), 'company_has_list': int((m & listed).sum()),
                      'linked': int((m & hit).sum()), 'linked_by_name_before_bracket': int((m & by_alt).sum())}
    p = t['person_role'].isin(PROMOTER_ROLES) & listed
    rep['promoter_filings']['link_rate_where_listed'] = round(float(hit[p].mean()) * 100, 1) if p.any() else None
    un = t[p & ~hit].drop_duplicates(['isin', 'person_id'])
    rep['promoter_filings']['unlinked_filers'] = int(len(un))
    rep['promoter_filings']['unlinked_examples'] = [
        f'{s}: {n}' for s, n in zip(un.get('nse_symbol', un['isin']).astype(str), un['person_name'].astype(str))][:20]
    return t, rep


def mark_allottee_promoters(allottees: pd.DataFrame, group: pd.DataFrame | None,
                            trades: pd.DataFrame | None) -> tuple[pd.DataFrame, dict]:
    """Adds `in_promoter_group` to preferential allottees: the allottee is in the company's latest promoter-group
    list (by name, or the name before a bracket) or filed under PIT as the company's promoter or promoter group.
    The issue XBRL names each allottee but not whether it is a promoter, so a mixed issue ("promoters and
    others") said nothing of how much went to the promoters (audit 23 Oct: Spectrum Electrical's 8.04% to
    "promoters and others" at 45.8% below the price). Matched by identity only, as `link`."""
    a = allottees.copy()
    a['in_promoter_group'] = False
    if a.empty or 'allottee_id' not in a:
        return a, {'allottees': 0}
    lists = latest_lists(group)
    members = (set(zip(lists['co'], lists['member_id'])) | set(zip(lists['co'], lists['member_alt_id'].dropna()))
               if not lists.empty else set())
    if trades is not None and not trades.empty:
        p = trades[trades['person_role'].isin(PROMOTER_ROLES)]
        members |= set(zip(p['isin'], p['person_id']))
    alts = a['allottee'].map(alt_key) if 'allottee' in a else pd.Series(None, index=a.index)
    hit = [k in members or (x is not None and (i, x) in members) for k, i, x in zip(zip(a['isin'], a['allottee_id']), a['isin'], alts)]
    a['in_promoter_group'] = pd.Series(hit, index=a.index, dtype=bool)
    listed = a['isin'].isin(set(lists['co'])) if not lists.empty else pd.Series(False, index=a.index)
    return a, {'allottees': int(len(a)), 'company_has_list': int(listed.sum()), 'in_promoter_group': int(a['in_promoter_group'].sum())}


def mark_deal_promoters(deals: pd.DataFrame, group: pd.DataFrame | None,
                        trades: pd.DataFrame | None) -> tuple[pd.DataFrame, dict]:
    """Adds `client_is_promoter` to bulk/block deals: the client is in the company's latest promoter-group list
    (by name, or the name before a bracket) or filed under PIT as the company's promoter or promoter group. Such a
    deal is the promoter's own trade, never a fund's, whatever the name looks like (audit 22 Oct: Fosun Pharma
    Industrial Pte, Gland Pharma's promoter, sold 1,74,02,500 shares on BSE on 04 Sep 2026, Rs 4,921 Cr, and Today
    read it as "Funds selling"). `client_promoter_basis`: 'promoter_group_list' or 'pit_filing'."""
    d = deals.copy()
    d['client_is_promoter'] = False
    d['client_promoter_basis'] = None
    if d.empty:
        return d, {'legs': 0}
    pairs = list(zip(d['isin'], d['client_id']))
    alts = list(zip(d['isin'], d['client_name'].map(alt_key) if 'client_name' in d else [None] * len(d)))
    lists = latest_lists(group)
    members = (set(zip(lists['co'], lists['member_id'])) | set(zip(lists['co'], lists['member_alt_id'].dropna()))
               if not lists.empty else set())
    filed = set()
    if trades is not None and not trades.empty:
        p = trades[trades['person_role'].isin(PROMOTER_ROLES)]
        filed = set(zip(p['isin'], p['person_id']))
    in_list = pd.Series([k in members or (a[1] is not None and a in members) for k, a in zip(pairs, alts)],
                        index=d.index, dtype=bool)
    in_pit = pd.Series([k in filed for k in pairs], index=d.index, dtype=bool) & ~in_list
    d.loc[in_list | in_pit, 'client_is_promoter'] = True
    d.loc[in_list, 'client_promoter_basis'] = 'promoter_group_list'
    d.loc[in_pit, 'client_promoter_basis'] = 'pit_filing'
    return d, {'legs': int((in_list | in_pit).sum()), 'by_list': int(in_list.sum()), 'by_pit_filing': int(in_pit.sum())}

