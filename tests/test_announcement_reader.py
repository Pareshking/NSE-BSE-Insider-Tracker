"""The announcement reader (scripts/announcement_reader.py): checks on each value, read-once rules, lanes
falling back, and the reads written to an in-memory R2. No model or exchange is called."""
from __future__ import annotations

import io
import json
import zipfile
from datetime import date, datetime, timezone

import announcement_reader as ar
import announcement_sample as sample
import pandas as pd
import pytest
from test_archive_and_writer import FakeR2

DOC = ('Allotment of 1,81,10,473 Equity Shares at the issue price of Rs. 165.65 per Equity Share to Qualified '
       'Institutional Buyers, aggregating to Rs. 299,99,99,852.45 (Rupees Two Hundred Ninety-Nine Crore). '
       'The Record Date is October 1, 2026. Hyundai plans an investment of USD 15.5 billion by 2030.')


def test_values_are_shown_only_when_their_quote_digits_and_unit_hold():
    out = {'category': 'qip', 'fields': [
        {'name': 'price_per_share', 'value': '165.65', 'quote': 'at the issue price of Rs. 165.65 per Equity Share'},
        {'name': 'shares', 'value': '1,81,10,473', 'quote': 'Allotment of 1,81,10,473 Equity Shares'},
        {'name': 'amount', 'value': '299,99,99,852.45', 'quote': 'aggregating to Rs. 299,99,99,852.45 (Rupees'},
        {'name': 'amount_unit', 'value': 'crore', 'quote': 'Rupees Two Hundred Ninety-Nine Crore'},
        {'name': 'record_date', 'value': 'October 1, 2026', 'quote': 'The Record Date is October 1, 2026'},
        {'name': 'entity', 'value': 'listed', 'quote': 'Allotment of 1,81,10,473 Equity Shares'},
        {'name': 'discount_pct', 'value': '5', 'quote': 'a discount of 5% to the floor price'}],
        'metrics': [{'label': 'investment', 'period': '2030', 'value': '15.5', 'unit': 'billion',
                     'quote': 'an investment of USD 15.5 billion by 2030'}]}
    cat, fields, metrics = ar.validate(out, DOC)
    f = {x['name']: x for x in fields}
    assert cat == 'qip'
    assert f['price_per_share']['shown'] and f['price_per_share']['number'] == 165.65
    assert f['shares']['shown'] and f['shares']['number'] == 18110473 and f['shares']['evidence'] == 'exact'
    assert not f['amount']['shown'] and 'unit not backed' in f['amount']['reason']   # crore only in the words
    assert f['record_date']['shown'] and f['record_date']['date'] == '2026-10-01'
    assert not f['entity']['shown'] and f['entity']['reason'] == 'entity labels not shown yet'
    assert not f['discount_pct']['shown'] and 'quote not found' in f['discount_pct']['reason']
    assert metrics[0]['shown'] and metrics[0]['number'] == 15.5e9
    _, fields, _ = ar.validate({'fields': [{'name': 'amount', 'value': '15.5',
                                            'quote': 'an investment of USD 15.5 billion by 2030'}]}, DOC)
    assert not fields[0]['shown']   # unit left out: 15.5 is not the amount
    assert ar.validate(None, DOC) == (None, [], [])


def test_second_reader_agreement_per_shown_field():
    main = [{'name': 'price_per_share', 'shown': True, 'number': 165.65},
            {'name': 'record_date', 'shown': True, 'date': '2026-10-01'},
            {'name': 'shares', 'shown': True, 'number': 100}, {'name': 'amount', 'shown': False, 'number': 1}]
    second = [{'name': 'price_per_share', 'number': 165.65}, {'name': 'record_date', 'date': '2026-10-02'}]
    assert ar.agreement(main, second) == {'price_per_share': True, 'record_date': False, 'shares': None}


def _cand(eid, exchange, isin, at, subject, detail='', group='fund_raise', mcap=5e10, **kw):
    return {'event_id': eid, 'exchange': exchange, 'market': 'equities', 'isin': isin, 'symbol': 'X', 'company': 'X Ltd',
            'subject': subject, 'detail': detail, 'group': group, 'file_url': f'https://f/{eid}.pdf', 'file_type': 'pdf',
            'broadcast_at': at, 'broadcast_date': at[:10], 'market_cap': mcap, **kw}




def test_candidates_resolves_nan_isin_before_market_cap_filter():
    class Master:
        market_cap_as_of = '2026-10-14'
        def resolve(self, exchange, identifier):
            if exchange == 'nse' and identifier == 'BANKBARODA':
                return ('INE028A01039', 'symbol')
            return (None, None)
        def record(self, isin):
            if isin == 'INE028A01039':
                return {'market_cap': 2_000_000_000_000, 'nse_symbol': 'BANKBARODA'}
            return None

    nse = pd.DataFrame([
        {'event_id': 'nse:cap-map', 'symbol': 'BANKBARODA', 'isin': float('nan'),
         'company': 'Bank of Baroda', 'subject': 'Acquisition', 'text': 'Announcement',
         'file_url': 'https://nsearchives.nseindia.com/corporate/bankbaroda.pdf',
         'file_type': 'pdf', 'has_xbrl': False, 'broadcast_at': '2026-10-15T09:00:00+05:30',
         'broadcast_date': '2026-10-15', 'market': 'equities'},
        {'event_id': 'nse:stale-isin', 'symbol': 'BANKBARODA', 'isin': 'INEOLD000000',
         'company': 'Bank of Baroda', 'subject': 'Acquisition', 'text': 'Announcement',
         'file_url': 'https://nsearchives.nseindia.com/corporate/bankbaroda-stale.pdf',
         'file_type': 'pdf', 'has_xbrl': False, 'broadcast_at': '2026-10-15T09:01:00+05:30',
         'broadcast_date': '2026-10-15', 'market': 'equities'},
    ])
    out = ar.candidates(nse, pd.DataFrame(), Master()).set_index('event_id')
    assert out.loc['nse:cap-map', 'isin'] == 'INE028A01039'
    assert out.loc['nse:cap-map', 'market_cap'] == 2_000_000_000_000
    assert out.loc['nse:cap-map', 'market_cap_match'] == 'isin'
    assert out.loc['nse:stale-isin', 'isin'] == 'INEOLD000000'  # preserve source identity
    assert out.loc['nse:stale-isin', 'market_cap'] == 2_000_000_000_000
    assert out.loc['nse:stale-isin', 'market_cap_match'] == 'exchange_symbol'
    assert set(out['market_cap_as_of']) == {'2026-10-14'}

def test_candidates_prefers_related_nse_xbrl_attachment_and_suppresses_duplicate_read():
    rows = pd.DataFrame([
        {'event_id': 'pdf:1', 'symbol': 'X', 'isin': 'INE000A01000', 'company': 'X Ltd',
         'subject': 'Buyback', 'text': 'Buyback approved', 'file_url': 'https://nsearchives.nseindia.com/corporate/X_buyback.pdf',
         'file_type': 'pdf', 'has_xbrl': True, 'broadcast_at': '2026-10-14T10:00:00+05:30',
         'broadcast_date': '2026-10-14', 'market': 'equities'},
        {'event_id': 'xbrl:1', 'symbol': 'X', 'isin': 'INE000A01000', 'company': 'X Ltd',
         'subject': 'Buyback-XBRL', 'text': 'Structured buyback filing', 'file_url': 'https://nsearchives.nseindia.com/corporate/xbrl/X_buyback.xml',
         'file_type': 'xml', 'has_xbrl': False, 'broadcast_at': '2026-10-14T10:02:00+05:30',
         'broadcast_date': '2026-10-14', 'market': 'equities'},
        {'event_id': 'pdf:other', 'symbol': 'X', 'isin': 'INE000A01000', 'company': 'X Ltd',
         'subject': 'Director Resignation', 'text': 'A different filing by the same issuer on the same day',
         'file_url': 'https://nsearchives.nseindia.com/corporate/X_director.pdf',
         'file_type': 'pdf', 'has_xbrl': False, 'broadcast_at': '2026-10-14T10:03:00+05:30',
         'broadcast_date': '2026-10-14', 'market': 'equities'},
        {'event_id': 'pdf:2', 'symbol': 'Y', 'isin': 'INE000B01000', 'company': 'Y Ltd',
         'subject': 'General Updates', 'text': 'Financial filing', 'file_url': 'https://nsearchives.nseindia.com/corporate/Y_financials.pdf',
         'file_type': 'pdf', 'has_xbrl': True, 'broadcast_at': '2026-10-14T11:00:00+05:30',
         'broadcast_date': '2026-10-14', 'market': 'equities'},
        {'event_id': 'xbrl:2', 'symbol': 'Y', 'isin': 'INE000B01000', 'company': 'Y Ltd',
         'subject': 'Financial Results-XBRL', 'text': 'Structured financial filing', 'file_url': 'https://nsearchives.nseindia.com/corporate/xbrl/Y_financials.xml',
         'file_type': 'xml', 'has_xbrl': False, 'broadcast_at': '2026-10-14T11:02:00+05:30',
         'broadcast_date': '2026-10-14', 'market': 'equities'},
    ])
    out = ar.candidates(rows, pd.DataFrame(), None).set_index('event_id')
    assert out.loc['pdf:1', 'file_url'].endswith('X_buyback.pdf')  # preserve original announcement link
    assert out.loc['pdf:1', 'content_url'].endswith('X_buyback.xml')
    assert out.loc['pdf:1', 'xbrl_source_event_id'] == 'xbrl:1'
    assert out.loc['pdf:1', 'xbrl_source_url'].endswith('X_buyback.xml')
    assert out.loc['xbrl:1', 'group'] == 'routine'  # one model read, using the structured source
    assert out.loc['pdf:other', 'content_url'].endswith('X_director.pdf')  # unrelated filing stays separate
    assert pd.isna(out.loc['pdf:other', 'xbrl_source_event_id'])
    assert out.loc['pdf:2', 'content_url'].endswith('Y_financials.pdf')  # subject mismatch without filing-ID proof stays PDF
    assert pd.isna(out.loc['pdf:2', 'xbrl_source_event_id'])
    assert out.loc['xbrl:2', 'group'] == 'routine'



def test_candidates_do_not_pair_generic_zip_documents_as_xbrl():
    rows = pd.DataFrame([
        {'event_id': 'pdf:1', 'symbol': 'X', 'isin': 'INE000A01000', 'company': 'X Ltd',
         'subject': 'Resignation of Director/KMP/SMP', 'text': 'Resignation notice',
         'file_url': 'https://nsearchives.nseindia.com/corporate/X_ROID_100473_KMP_Doc.pdf',
         'file_type': 'pdf', 'has_xbrl': True, 'broadcast_at': '2026-10-14T10:00:00+05:30',
         'broadcast_date': '2026-10-14', 'market': 'equities'},
        {'event_id': 'zip:1', 'symbol': 'X', 'isin': 'INE000A01000', 'company': 'X Ltd',
         'subject': 'Resignation of Director/KMP/SMP', 'text': 'KMP attachment',
         'file_url': 'https://nsearchives.nseindia.com/corporate/X_ROID_100473_KMP_Doc.zip',
         'file_type': 'zip', 'has_xbrl': False, 'broadcast_at': '2026-10-14T10:01:00+05:30',
         'broadcast_date': '2026-10-14', 'market': 'equities'},
    ])
    out = ar.candidates(rows, pd.DataFrame(), None).set_index('event_id')
    assert out.loc['pdf:1', 'content_url'].endswith('X_ROID_100473_KMP_Doc.pdf')
    assert pd.isna(out.loc['pdf:1', 'xbrl_source_event_id'])


def test_candidates_reject_ambiguous_exact_subject_xbrl_matches():
    rows = pd.DataFrame([
        {'event_id': 'pdf:1', 'symbol': 'X', 'isin': 'INE000A01000', 'company': 'X Ltd',
         'subject': 'Financial Results', 'text': 'Results', 'file_url': 'https://nsearchives.nseindia.com/corporate/X.pdf',
         'file_type': 'pdf', 'has_xbrl': True, 'broadcast_at': '2026-10-14T10:00:00+05:30',
         'broadcast_date': '2026-10-14', 'market': 'equities'},
        {'event_id': 'xml:1', 'symbol': 'X', 'isin': 'INE000A01000', 'company': 'X Ltd',
         'subject': 'Financial Results', 'text': 'Structured results', 'file_url': 'https://nsearchives.nseindia.com/corporate/X1.xml',
         'file_type': 'xml', 'has_xbrl': False, 'broadcast_at': '2026-10-14T10:01:00+05:30',
         'broadcast_date': '2026-10-14', 'market': 'equities'},
        {'event_id': 'xml:2', 'symbol': 'X', 'isin': 'INE000A01000', 'company': 'X Ltd',
         'subject': 'Financial Results', 'text': 'Structured results', 'file_url': 'https://nsearchives.nseindia.com/corporate/X2.xml',
         'file_type': 'xml', 'has_xbrl': False, 'broadcast_at': '2026-10-14T10:02:00+05:30',
         'broadcast_date': '2026-10-14', 'market': 'equities'},
    ])
    out = ar.candidates(rows, pd.DataFrame(), None).set_index('event_id')
    assert out.loc['pdf:1', 'content_url'].endswith('X.pdf')
    assert pd.isna(out.loc['pdf:1', 'xbrl_source_event_id'])


def test_nse_parser_preserves_exchange_supplied_xbrl_url():
    from collectors.nse_events import announcements as nann
    url = 'https://nsearchives.nseindia.com/corporate/xbrl/X.xml'
    assert nann._xbrl_file({'hasXbrl': True, 'xbrlUrl': url, 'attchmntFile': 'https://nsearchives.nseindia.com/corporate/X.pdf'}) == url
    assert nann._xbrl_file({'hasXbrl': True, 'attchmntFile': 'https://nsearchives.nseindia.com/corporate/X.pdf'}) is None


def test_candidates_use_exchange_supplied_xbrl_url_directly():
    nse = pd.DataFrame([{
        'event_id': 'nse:direct-xbrl', 'symbol': 'X', 'isin': 'INE000A01000', 'company': 'X Ltd',
        'subject': 'Financial Results', 'text': 'Results announcement',
        'file_url': 'https://nsearchives.nseindia.com/corporate/X.pdf',
        'xbrl_url': 'https://nsearchives.nseindia.com/corporate/xbrl/X.xml',
        'file_type': 'pdf', 'has_xbrl': True, 'broadcast_at': '2026-10-14T10:00:00+05:30',
        'broadcast_date': '2026-10-14', 'market': 'equities',
    }])
    row = ar.candidates(nse, pd.DataFrame(), None).iloc[0]
    assert row['file_url'].endswith('X.pdf')
    assert row['content_url'].endswith('X.xml')
    assert row['xbrl_source_event_id'] == 'nse:direct-xbrl'
    assert row['xbrl_source_url'].endswith('X.xml')


def test_xbrl_audit_reports_flags_attachments_and_links():
    cands = pd.DataFrame([
        {'event_id': 'pdf:1', 'exchange': 'NSE', 'symbol': 'X', 'isin': 'INE000A01000',
         'subject': 'General Updates', 'broadcast_date': '2026-10-14', 'file_type': 'pdf',
         'has_xbrl': True, 'file_url': 'https://nsearchives.nseindia.com/corporate/X.pdf',
         'xbrl_url': 'https://nsearchives.nseindia.com/corporate/xbrl/X.xml',
         'content_url': 'https://nsearchives.nseindia.com/corporate/xbrl/X.xml',
         'xbrl_source_event_id': 'xbrl:1', 'xbrl_source_url': 'https://nsearchives.nseindia.com/corporate/xbrl/X.xml'},
        {'event_id': 'xbrl:1', 'exchange': 'NSE', 'symbol': 'X', 'isin': 'INE000A01000',
         'subject': 'General Updates', 'broadcast_date': '2026-10-14', 'file_type': 'xml',
         'has_xbrl': False, 'file_url': 'https://nsearchives.nseindia.com/corporate/xbrl/X.xml',
         'content_url': 'https://nsearchives.nseindia.com/corporate/xbrl/X.xml',
         'xbrl_source_event_id': None, 'xbrl_source_url': None},
    ])
    audit = ar.xbrl_audit(cands)
    assert audit['candidates'] == 2
    assert audit['has_xbrl_flagged'] == 1
    assert audit['direct_xbrl_urls'] == 1
    assert audit['xbrl_attachments'] == 1  # XML format counts even without an XBRL subject label
    assert audit['xbrl_subject_labels'] == 0
    assert audit['xbrl_linked'] == 1
    assert audit['linked_samples'][0]['xbrl_source_event_id'] == 'xbrl:1'

def test_choose_excludes_unverified_market_cap_and_keeps_exactly_100_cr():
    today = date(2026, 10, 13)
    c = pd.DataFrame([
        _cand('below', 'NSE', 'INELOW', '2026-10-13T10:00:00+05:30', 'Buyback', mcap=999_999_999),
        _cand('boundary', 'NSE', 'INE100', '2026-10-13T10:01:00+05:30', 'Buyback', mcap=1_000_000_000),
        _cand('unknown', 'NSE', 'INEUNK', '2026-10-13T10:02:00+05:30', 'Buyback', mcap=None),
    ])
    to_read, status, counts = ar.choose(c, None, today)
    assert list(to_read['event_id']) == ['boundary']
    statuses = status.set_index('event_id')['status'].to_dict()
    assert statuses == {'below': 'below_100_cr', 'unknown': 'market_cap_unverified'}
    assert counts['below_100_cr'] == 1
    assert counts['market_cap_unverified'] == 1


def test_choose_reads_once_skips_small_and_routine_and_retries_failures():
    today = date(2026, 10, 13)
    c = pd.DataFrame([
        _cand('nse:1', 'NSE', 'INE1', '2026-10-13T10:00:00+05:30', 'Preferential issue', 'Allotment of warrants to promoters'),
        _cand('bse:a', 'BSE', 'INE1', '2026-10-13T10:02:00+05:30', 'Preferential Issue', 'Allotment of warrants'),
        _cand('nse:2', 'NSE', 'INE2', '2026-10-13T11:00:00+05:30', 'Trading Window', group='routine'),
        _cand('nse:3', 'NSE', 'INE3', '2026-10-13T12:00:00+05:30', 'Buyback', mcap=5e8),
        _cand('nse:4', 'NSE', 'INE4', '2026-10-12T09:00:00+05:30', 'Rights Issue'),
        _cand('nse:5', 'NSE', 'INE5', '2026-10-10T09:00:00+05:30', 'Rights Issue'),   # older than yesterday
        _cand('nse:6', 'NSE', 'INE6', '2026-10-13T13:00:00+05:30', 'Buyback'),
        _cand('nse:7', 'NSE', 'INE7', '2026-10-13T14:00:00+05:30', 'Buyback')])
    done = pd.DataFrame([{**_cand('nse:6', 'NSE', 'INE6', '2026-10-13T13:00:00+05:30', 'Buyback'), 'status': 'read', 'tries': 1,
                          'prompt_version': ar.PROMPT_VERSION},
                         {**_cand('nse:7', 'NSE', 'INE7', '2026-10-13T14:00:00+05:30', 'Buyback'), 'status': 'failed', 'tries': 1}])
    to_read, status, counts = ar.choose(c, done, today)
    assert list(to_read['event_id']) == ['nse:7', 'nse:1', 'nse:4']   # today newest first, then yesterday
    assert to_read.set_index('event_id')['tries']['nse:7'] == 1          # a failure is tried again
    st = status.set_index('event_id')
    assert st.loc['bse:a', 'status'] == 'same_filing_other_exchange' and st.loc['bse:a', 'same_as'] == 'nse:1'
    assert st.loc['nse:3', 'status'] == 'below_100_cr'
    assert counts == {'candidates': 7, 'routine_or_no_file': 1, 'already_done': 1, 'below_100_cr': 1,
                      'market_cap_unverified': 0, 'same_filing_other_exchange': 1, 'to_read': 3}
    gave_up = done.assign(tries=ar.MAX_TRIES)
    assert 'nse:7' not in set(ar.choose(c, gave_up, today)[0]['event_id'])


def test_permanent_missing_document_is_retired_after_one_attempt():
    today = date(2026, 10, 13)
    candidate = pd.DataFrame([_cand('bse:missing', 'BSE', 'INE404',
                                    '2026-01-01T10:00:00+05:30', 'Credit Rating')])
    lanes = {'nvidia': ar.Lane('nvidia', ['nvidia:m'], {'nvidia': FakeClient([])})}

    def missing(_url):
        raise RuntimeError('HTTP 404 8,420 bytes')

    rows, _ = ar.run(candidate, lanes, None, 10, fetch=missing, max_filings=1, idle_wait=0.001)
    assert len(rows) == 1
    assert rows[0]['status'] == 'failed'
    assert rows[0]['tries'] == ar.MAX_TRIES
    assert 'permanent missing document; no retry' in rows[0]['reason']
    done = pd.DataFrame(rows)
    assert ar.choose(candidate, done, today, date_from=date(2026, 1, 1), date_to=date(2026, 1, 1))[0].empty


def test_different_subjects_or_hours_apart_are_not_the_same_filing():
    a = _cand('nse:1', 'NSE', 'INE1', '2026-10-13T10:00:00+05:30', 'Outcome of Board Meeting', 'approved fund raising by QIP')
    assert ar.same_filing(a, _cand('bse:1', 'BSE', 'INE1', '2026-10-13T10:05:00+05:30', 'Outcome of Board Meeting', 'QIP fund raising approved'))
    assert not ar.same_filing(a, _cand('bse:2', 'BSE', 'INE1', '2026-10-13T10:05:00+05:30', 'Credit Rating', 'rating reaffirmed'))
    assert not ar.same_filing(a, _cand('bse:3', 'BSE', 'INE1', '2026-10-13T19:00:00+05:30', 'Outcome of Board Meeting', 'approved fund raising by QIP'))
    assert not ar.same_filing(a, {**a, 'event_id': 'nse:9'})   # same exchange: two filings


def test_text_of_prefers_valid_xbrl_inside_zip_over_pdf(monkeypatch):
    xml = b'''<?xml version="1.0" encoding="UTF-8"?>
    <xbrli:xbrl xmlns:xbrli="http://www.xbrl.org/2003/instance" xmlns:in="urn:example">
      <xbrli:context id="FY">
        <xbrli:entity><xbrli:identifier scheme="urn:test">ACME</xbrli:identifier></xbrli:entity>
        <xbrli:period><xbrli:startDate>2026-04-01</xbrli:startDate><xbrli:endDate>2026-09-30</xbrli:endDate></xbrli:period>
      </xbrli:context>
      <xbrli:unit id="INR"><xbrli:measure>iso4217:INR</xbrli:measure></xbrli:unit>
      <in:Revenue contextRef="FY" unitRef="INR" decimals="0">1250000000</in:Revenue>
    </xbrli:xbrl>'''
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, 'w') as z:
        z.writestr('instance.xml', xml)
        z.writestr('filing.pdf', b'not actually a PDF')
    monkeypatch.setattr(ar.s, 'pdf_text', lambda _data: (_ for _ in ()).throw(AssertionError('PDF fallback used')))
    text, notes = ar.s.text_of(archive.getvalue())
    assert 'XBRL FACTS' in text and 'Revenue = 1250000000' in text
    assert '2026-04-01' in text and '2026-09-30' in text
    assert any(note.startswith('xbrl: instance.xml') for note in notes)


def test_security_master_uses_latest_market_cap_snapshot_not_after_requested_date(monkeypatch):
    import collectors.nse_events.run_daily as run_daily
    requests = []
    payload = [{'symbol': '500325', 'isin': 'INE002A01018', 'company_name': 'ACME',
                'market_cap': 1_000_000_000, 'source': 'bse_list_securities'}]
    def get_snapshot(_r2, key):
        requests.append(key)
        return json.dumps(payload).encode() if key.endswith('/2026-10-14/data.json') else None
    monkeypatch.setattr(run_daily, 'get', get_snapshot)
    monkeypatch.setattr(run_daily, 'nse_lists', lambda *_: (pd.DataFrame(), pd.DataFrame()))
    master = run_daily.security_master(object(), '2026-10-15', [])
    assert master.market_cap_as_of == '2026-10-14'
    assert master.record('INE002A01018')['market_cap'] == 1_000_000_000
    assert requests[:2] == ['reference/market_cap/2026-10-15/data.json',
                            'reference/market_cap/2026-10-14/data.json']


class FakeClient:
    def __init__(self, replies):
        self.replies, self.attempts, self.asked = list(replies), [], []

    def generate(self, models, prompt, kind, json_mode):
        self.asked.append(models[0])
        r = self.replies.pop(0)
        if isinstance(r, Exception):
            self.attempts.append((models[0], 'ReadTimeout', 300.0))
            raise r
        self.attempts.append((models[0], 200, 12.5))
        return r, {}, models[0]


QIP = json.dumps({'category': 'qip', 'fields': [
    {'name': 'price_per_share', 'value': '165.65', 'quote': 'at the issue price of Rs. 165.65 per Equity Share'}]})


def test_lane_falls_back_and_leaves_out_a_model_that_keeps_timing_out():
    slow = RuntimeError('all nvidia read models busy or refused (moonshotai/kimi-k3: ReadTimeout)')
    c = FakeClient([slow, QIP, slow, QIP, QIP])
    lane = ar.Lane('main', ['nvidia:moonshotai/kimi-k3', 'nvidia:google/gemma-4-31b-it'], {'nvidia': c})
    assert lane.read('p')[1] == 'nvidia:google/gemma-4-31b-it'
    lane.read('p')
    assert lane.dropped == ['nvidia:moonshotai/kimi-k3']
    lane.read('p')
    assert c.asked == ['moonshotai/kimi-k3', 'google/gemma-4-31b-it'] * 2 + ['google/gemma-4-31b-it']
    use = ar.usage({'nvidia': c}, {'main': lane})
    assert use['models']['nvidia:google/gemma-4-31b-it'] == {'calls': 3, 'by_status': {'200': 3}, 'median_seconds_ok': 12.5}
    assert use['left_out_as_slow'] == {'main': ['nvidia:moonshotai/kimi-k3']}


def test_rate_limited_model_is_circuit_broken_and_fallback_continues():
    limited = RuntimeError('provider returned HTTP 429: rate limit reached for tokens per day')
    groq = FakeClient([limited])
    nvidia = FakeClient([QIP])
    lane = ar.Lane('main', ['groq:qwen/qwen3.8-27b', 'nvidia:moonshotai/kimi-k3'],
                   {'groq': groq, 'nvidia': nvidia})
    assert lane.read('p')[1] == 'nvidia:moonshotai/kimi-k3'
    assert lane.dropped == ['groq:qwen/qwen3.8-27b']
    assert lane.rate_limited == ['groq:qwen/qwen3.8-27b']
    assert ('groq', 'qwen/qwen3.8-27b') not in lane.models()


def test_rate_limit_circuit_breaker_persists_for_day(monkeypatch):
    import clean_writer
    store = {}
    monkeypatch.setattr(clean_writer, 'get', lambda r2, key: store.get(key))
    monkeypatch.setattr(clean_writer, 'put', lambda r2, key, body, content_type=None: store.__setitem__(
        key, body.decode() if isinstance(body, bytes) else body))
    lane = ar.Lane('groq', ['groq:qwen/qwen3.8-27b'], {'groq': FakeClient([])})
    ar.configure_rate_limit_circuit_breaker({'groq': lane}, object(), '2026-10-14')
    lane.on_rate_limit('groq:qwen/qwen3.8-27b', 'HTTP 429 tokens per day')
    assert 'groq:qwen/qwen3.8-27b' in ar.load_rate_limited_models(object(), '2026-10-14')
    other = ar.Lane('groq', ['groq:qwen/qwen3.8-27b'], {'groq': FakeClient([])})
    ar.configure_rate_limit_circuit_breaker({'groq': other}, object(), '2026-10-14')
    assert other.models() == []
    assert other.rate_limited == ['groq:qwen/qwen3.8-27b']

def test_lanes_file_and_free_only_rule():
    spec = ar.lanes_of(ar.LANES_FILE.read_text(encoding='utf-8'))
    assert list(spec) == ['nvidia', 'zai', 'groq', 'gemini'] and all(spec.values())
    assert all({e.split(':', 1)[0] for e in es} == {name} for name, es in spec.items())   # one provider a lane
    assert ar.usable(['zai:glm-4.5-flash', 'zai:glm-5.3', 'nvidia:moonshotai/kimi-k3']) == [
        'zai:glm-4.5-flash', 'nvidia:moonshotai/kimi-k3']
    _, notes = ar.clients_for(['zai:glm-5.3'], env={'ZAI_API_KEY': 'k'})
    assert any('not one of zai' in n for n in notes)
    assert ar.clients_for(['nvidia:x'], env={})[1] == ['NVIDIA_API_KEY is not set; nvidia lanes skipped']
    assert isinstance(ar.clients_for(['gemini:gemini-3.5-flash-lite'], env={'GEMINI_API_KEY': 'k'})[0]['gemini'],
                      ar.GeminiCalls)


def _lanes(**replies):
    """Lanes named after their provider, each with a fake client answering in turn."""
    return {p: ar.Lane(p, [f'{p}:m'], {p: FakeClient(r)}) for p, r in replies.items()}


def _qips(n):
    return pd.DataFrame([_cand(f'nse:{i}', 'NSE', f'INE{i}', f'2026-10-13T1{i}:00:00+05:30', 'QIP') for i in range(1, n + 1)])


def test_lanes_read_different_filings_at_once_copy_the_same_file_and_cross_check_when_idle(monkeypatch):
    monkeypatch.setattr(ar.s, 'text_of', lambda data: (DOC if data != b'empty' else '', ['0.1 MB']))
    files = {'https://f/nse:1.pdf': b'one', 'https://f/nse:2.pdf': b'one', 'https://f/nse:3.pdf': b'empty'}
    lanes = _lanes(nvidia=[QIP, QIP], zai=[QIP, QIP])
    rows, notes = ar.run(_qips(3), lanes, None, 600, fetch=files.__getitem__, idle_wait=0.01)
    by = {r['event_id']: r for r in rows}
    # nse:1 and nse:2 are one file, taken by two lanes at once: the first downloaded is read, the other
    # waits for that read and is copied from it, never read twice
    read, copy = sorted((by['nse:1'], by['nse:2']), key=lambda r: r['status'] != 'read')
    assert read['status'] == 'read' and read['shown'] == 1 and json.loads(read['fields'])[0]['number'] == 165.65
    assert copy['status'] == 'same_file' and copy['same_as'] == read['event_id'] and copy['fields'] == read['fields']
    assert by['nse:3']['status'] == 'no_text'
    # the idle lane, of the other provider, read it again: its one shown value agrees
    other = ({'nvidia', 'zai'} - {read['reader'].split(':')[0]}).pop()
    assert read['second_reader'] == f'{other}:m' and json.loads(read['agreed']) == {'price_per_share': True}
    assert notes == {'not_reached': 0, 'cross_checked': 1} and len(rows) == 3
    assert sum(len(lane.clients[n].asked) for n, lane in lanes.items()) == 2   # one read, one cross-check
    r2 = FakeR2()
    assert ar.write(r2, rows, '2026-10-13', date(2026, 10, 13)) == 3
    clean = pd.read_parquet(io.BytesIO(r2.objects[ar.CLEAN_KEY]))
    assert set(clean['event_id']) == {'nse:1', 'nse:2', 'nse:3'} and 'exchange' in clean and 'category' in clean
    again = [dict(rows[-1], status='read', tries=2)]
    assert ar.write(r2, again, '2026-10-13', date(2026, 10, 13)) == 0   # replaced, not added


def test_a_filing_one_lane_cannot_read_goes_to_another_and_fails_only_when_all_have_tried(monkeypatch):
    monkeypatch.setattr(ar.s, 'text_of', lambda data: (DOC + data.decode(), []))   # different filings
    boom = RuntimeError('all nvidia read models busy or refused (x: HTTP 503)')
    lanes = _lanes(nvidia=[boom] * 9, zai=[QIP, QIP, boom])
    rows, notes = ar.run(_qips(3), lanes, None, 600, fetch=lambda u: u.encode(), idle_wait=0.01)
    by = {r['event_id']: r for r in rows}
    read = [r for r in rows if r['status'] == 'read']
    assert len(read) == 2 and all(r['reader_lane'] == 'zai' for r in read)
    failed = [r for r in rows if r['status'] == 'failed']
    assert len(failed) == 1 and 'nvidia:' in failed[0]['reason'] and 'zai:' in failed[0]['reason']
    assert failed[0]['tries'] == 1 and set(by) == {'nse:1', 'nse:2', 'nse:3'} and notes['not_reached'] == 0


def test_a_lane_at_its_daily_limit_stops_and_hands_its_work_on(monkeypatch):
    monkeypatch.setattr(ar.s, 'text_of', lambda data: (DOC + data.decode(), []))
    monkeypatch.setattr(ar, 'DAILY_CALLS', {'groq:m': 100})
    lanes = _lanes(groq=[QIP] * 5, zai=[QIP] * 5)
    lanes['groq'].used_today = {'groq:m': 95}            # 95% of 100 already used today
    assert lanes['groq'].models() == [] and lanes['zai'].models() == [('zai', 'm')]
    rows, _ = ar.run(_qips(3), lanes, None, 600, fetch=lambda u: u.encode(), idle_wait=0.01)
    assert [r['reader_lane'] for r in rows] == ['zai'] * 3 and lanes['groq'].clients['groq'].asked == []


def test_all_lanes_at_daily_quota_leave_live_filings_pending(monkeypatch):
    monkeypatch.setattr(ar, 'DAILY_CALLS', {'groq:m': 100, 'zai:m': 100})
    lanes = _lanes(groq=[QIP] * 3, zai=[QIP] * 3)
    lanes['groq'].used_today = {'groq:m': 95}
    lanes['zai'].used_today = {'zai:m': 95}
    rows, notes = ar.run(_qips(3), lanes, None, 600, fetch=lambda u: u.encode(), idle_wait=0.01)
    assert rows == []  # no fake failures written just because today's free allowance is used
    assert notes['not_reached'] == 3
    assert lanes['groq'].clients['groq'].asked == []
    assert lanes['zai'].clients['zai'].asked == []


def test_quota_deferred_filing_does_not_spend_retry_budget_and_is_selected_again(monkeypatch):
    monkeypatch.setattr(ar.s, 'text_of', lambda data: (DOC + data.decode(), []))
    limited = RuntimeError('provider returned HTTP 429: rate limit reached for tokens per day')
    lane = ar.Lane('groq', ['groq:m'], {'groq': FakeClient([limited])})
    rows, notes = ar.run(_qips(1), {'groq': lane}, None, 600,
                         fetch=lambda u: u.encode(), idle_wait=0.01)
    assert len(rows) == 1
    assert rows[0]['status'] == 'quota_deferred'
    assert rows[0]['tries'] == 0
    done = pd.DataFrame([rows[0]])
    candidates = _qips(1)
    selected, _, _ = ar.choose(candidates, done, date(2026, 10, 13))
    assert selected['event_id'].tolist() == ['nse:1']


def test_quota_deferred_status_is_never_retired_by_max_tries():
    row = dict(_cand('nse:1', 'NSE', 'INE1', '2026-10-13T10:00:00+05:30', 'QIP'),
               status='quota_deferred', prompt_version=ar.PROMPT_VERSION, tries=ar.MAX_TRIES + 10)
    selected, _, _ = ar.choose(_qips(1), pd.DataFrame([row]), date(2026, 10, 13))
    assert selected['event_id'].tolist() == ['nse:1']


def test_time_budget_leaves_the_rest_for_the_next_run(monkeypatch):
    monkeypatch.setattr(ar.s, 'text_of', lambda data: (DOC, []))
    ticks = iter([0, 0, 1000])                            # start, first take, then time is up
    rows, notes = ar.run(_qips(3), _lanes(nvidia=[QIP]), None, 600, fetch=lambda u: u.encode(),
                         now=lambda: next(ticks, 1000))
    assert len(rows) == 1 and notes['not_reached'] == 2


def test_each_filing_is_saved_as_it_is_read_and_a_failed_save_waits_for_the_next(monkeypatch):
    monkeypatch.setattr(ar.s, 'text_of', lambda data: (DOC + data.decode(), []))
    lanes, to_read = _lanes(nvidia=[QIP, QIP, QIP]), _qips(3)
    r2, calls, clock = FakeR2(), [], iter([0, 20, 20, 25, 50])

    def writer(r2_, rows, run_date, today):
        calls.append([r['event_id'] for r in rows])
        if len(calls) == 2:
            raise OSError('R2 down')
        return ar.write(r2_, rows, run_date, today)
    saver = ar.Saver(r2, '2026-10-13', date(2026, 10, 13), every=15, now=lambda: next(clock), writer=writer)
    rows, _ = ar.run(to_read, lanes, None, 600, fetch=lambda u: u.encode(), on_row=saver.add)
    # nse:1 saved at once; nse:2's save fails and is kept; nse:3 comes 5 s later and waits; the last write has both
    assert calls == [['nse:1'], ['nse:2']] and [r['event_id'] for r in saver.pending] == ['nse:2', 'nse:3']
    saver.flush(final=True)
    assert calls[-1] == ['nse:2', 'nse:3'] and saver.pending == [] and saver.added == 3 and saver.writes == 2
    clean = pd.read_parquet(io.BytesIO(r2.objects[ar.CLEAN_KEY]))
    assert sorted(clean['event_id']) == ['nse:1', 'nse:2', 'nse:3'] and len(rows) == 3


def test_the_last_save_of_a_run_raises():
    def writer(*_):
        raise OSError('R2 down')
    saver = ar.Saver(FakeR2(), '2026-10-13', date(2026, 10, 13), writer=writer)
    saver.add({'event_id': 'nse:1'})   # the first save fails quietly and keeps the row
    with pytest.raises(OSError):
        saver.flush(final=True)


def test_headline_prompt_v2_is_opt_in_and_preserves_baseline():
    row = _cand('nse:prompt', 'NSE', 'INEPROMPT', '2026-10-13T10:00:00+05:30', 'Outcome of Board Meeting')
    baseline = ar.card_prompt(row, DOC, variant='baseline')
    experimental = ar.card_prompt(row, DOC, variant='v2')
    assert 'Lead with the approved or announced action' in baseline
    assert 'distinguish explicitly whether an action was approved, recommended, deferred, rejected' not in baseline
    assert 'distinguish explicitly whether an action was approved, recommended, deferred, rejected' in experimental
    assert 'never upgrade a proposal or recommendation to approval' in experimental
    assert 'return an empty headline rather than' in experimental
    assert 'Return the existing JSON schema only' in experimental
    assert '=== DOCUMENT ===' in baseline and '=== DOCUMENT ===' in experimental


def test_headline_prompt_v2_does_not_change_numeric_validation():
    text = 'Board recommends a dividend of Rs 5 per share'
    quote = 'The Board recommended a dividend of Rs 5 per share'
    assert ar.numbers_backed(text, [quote])
    assert not ar.numbers_backed('Board approves a dividend of Rs 50 per share', [quote])


@pytest.mark.parametrize('text', [
    'Madhav Infra Projects Ltd: Submission of Board Meeting Outcome for Board Meeting held today',
    'Outcome of Board Meeting for fund raising',
    'Company: Intimation of allotment',
    'Pursuant to Regulation 30 of SEBI LODR',
])
def test_exchange_filing_boilerplate_is_not_a_usable_headline(text):
    assert ar.headline_quality_reason(text)


def test_corporate_action_headlines_are_not_rejected_as_boilerplate():
    assert ar.headline_quality_reason('Madhav Infra approves preferential issue at Rs 8.15 a share') is None


@pytest.mark.parametrize('text,quote,ok', [
    ('Shivam Autotech sets ₹120 Cr rights issue at ₹12 per share', 'up to ₹ 12,000 Lakhs# ₹ 12 per Equity Share', True),
    ('Evonile Pharma approves rights issue of up to ₹900 Cr', 'for an aggregate amount not exceeding ₹9,000 million', True),
    ('16.45 lakh warrants at ₹152', 'up to 16,45,000 Warrants at an issue price of Rs. 152/-', True),
    ('FM Goetze approves ₹335 Cr capex', 'Investment Required Indian Rupees 3,351 Million', True),   # 335.1, rounded
    ('Sales up 32% in FY27', 'Sales FY 2026 812 FY 2027 1071', False),          # a growth rate of its own
    ('Raises ₹150 Cr', 'aggregating up to Rs. 25,00,40,000/-', False)])
def test_every_number_of_a_headline_or_point_must_be_in_its_quote(text, quote, ok):
    assert ar.numbers_backed(text, [quote]) is ok


def test_headline_points_and_year_ago_values_are_checked_against_the_filing():
    doc = ('the Board approved a Rights Issue of up to 10,00,00,000 Right Equity Shares. Issue Size up to ₹ 12,000 '
           'Lakhs. Issue Price ₹ 12 per Equity Share. Sales FY 2026 812 FY 2027 1071')
    out = {'category': 'rights', 'fields': [{'name': 'price_per_share', 'value': '12', 'quote': 'Issue Price ₹ 12 per Equity Share'}],
           'metrics': [{'label': 'Sales', 'period': 'Sep 2026', 'value': '1071', 'unit': 'units', 'quote': 'FY 2027 1071',
                        'previous': '812', 'previous_period': 'Sep 2025', 'previous_quote': 'FY 2026 812'}],
           'headline': {'text': 'Company sets ₹120 Cr rights issue at ₹12', 'quote': 'Issue Size up to ₹ 12,000 Lakhs'},
           'points': [{'text': 'Up to 10 Cr shares will be issued.', 'quote': 'up to 10,00,00,000 Right Equity Shares'},
                      {'text': 'Raising ₹500 Cr.', 'quote': 'Issue Size up to ₹ 12,000 Lakhs'},
                      {'text': 'Words the filing does not have.', 'quote': 'nowhere in it'}]}
    cat, fields, metrics = ar.validate(out, doc)
    metrics = [ar.with_previous(m, r, doc) for m, r in zip(metrics, out['metrics'])]
    headline, points = ar.card_words(out, doc, fields, metrics)
    assert headline['shown'] and [p['shown'] for p in points] == [True, False, False]
    boilerplate, _ = ar.card_words({**out, 'headline': {
        'text': 'Madhav Infra Projects Ltd: Submission of Board Meeting Outcome for Board Meeting held today',
        'quote': 'Issue Size up to ₹ 12,000 Lakhs'}}, doc, fields, metrics)
    assert boilerplate is not None and not boilerplate['shown']
    assert 'filing-label boilerplate' in boilerplate['reason']
    assert points[1]['reason'] == 'a number not in its quote' and points[2]['reason'] == 'quote not found in the filing'
    assert metrics[0]['previous_number'] == 812 and metrics[0]['change_pct'] == 31.9   # our sum, not the model's
    assert 'headline' in ar.card_prompt({'exchange': 'NSE', 'symbol': 'X', 'subject': 's'}, doc).split('=== DOCUMENT ===')[0]

@pytest.mark.parametrize('day,parts', [(date(2026, 10, 13), ['year=2026/month=09', 'year=2026/month=10']),
                                       (date(2026, 1, 1), ['year=2025/month=12', 'year=2026/month=01'])])
def test_two_months_of_archive_are_read(day, parts):
    assert ar.months_back(day) == parts


@pytest.mark.parametrize('value,quote,cur', [
    ('809', 'for an equity consideration of US$ 809mn (including', 'USD'), ('1.4', 'generated c.US$ 1.4bn of revenue', 'USD'),
    ('165.65', 'at the issue price of Rs. 165.65 per', 'INR'), ('28,200.00', 'not exceeding ₹ 28,200.00 Lakhs', 'INR'),
    ('5', 'a price of C$ 5 a share', 'CAD'), ('2', 'S$ 2 million', 'SGD'), ('200.00', 'Total 200.00', None)])
def test_currency_comes_from_the_quote_never_assumed(value, quote, cur):
    assert ar.currency_in_quote(value, quote) == cur


def test_each_money_value_carries_its_own_or_the_filings_currency():
    doc = 'consideration of US$ 809mn for the stake. Currency: USD. Issue price 120 per share'
    _, fields, metrics = ar.validate({'fields': [
        {'name': 'amount', 'value': '809', 'quote': 'consideration of US$ 809mn for the stake'},
        {'name': 'amount_unit', 'value': 'million', 'quote': 'US$ 809mn'},
        {'name': 'currency', 'value': 'USD', 'quote': 'Currency: USD'},
        {'name': 'price_per_share', 'value': '120', 'quote': 'Issue price 120 per share'}],
        'metrics': [{'label': 'x', 'value': '809', 'unit': 'million', 'quote': 'consideration of US$ 809mn for the stake'}]}, doc)
    f = {x['name']: x for x in fields}
    assert f['amount']['currency'] == 'USD' and f['price_per_share']['currency'] == 'USD'   # the filing's currency
    assert metrics[0]['currency'] == 'USD'



def test_a_cross_check_compares_figures_by_number_whatever_their_labels():
    main = [{'label': 'Sales Sep 2026', 'number': 1071, 'shown': True}, {'label': 'Exports', 'number': 53, 'shown': True},
            {'label': 'held', 'number': 9, 'shown': False}]
    second = [{'label': 'Commercial vehicle sales', 'number': 1071, 'shown': True}, {'label': 'x', 'number': 54, 'shown': True}]
    assert ar.metric_agreement(main, second) == {'metric:0': True, 'metric:1': None}



def test_a_read_with_an_older_prompt_is_read_again_once_and_never_copied():
    today = date(2026, 10, 13)
    c = pd.DataFrame([_cand('nse:1', 'NSE', 'INE1', '2026-10-13T10:00:00+05:30', 'Buyback'),
                      _cand('nse:2', 'NSE', 'INE2', '2026-10-13T11:00:00+05:30', 'Buyback')])
    done = pd.DataFrame([{**c.iloc[0].to_dict(), 'status': 'read', 'tries': 1, 'prompt_version': 'live-1'},
                         {**c.iloc[1].to_dict(), 'status': 'read', 'tries': 1, 'prompt_version': ar.PROMPT_VERSION}])
    assert list(ar.choose(c, done, today)[0]['event_id']) == ['nse:1']



def test_the_live_reader_asks_for_the_split_categories_and_still_knows_the_old_one():
    p = ar.card_prompt({'exchange': 'NSE', 'symbol': 'X', 'subject': 's'}, 'DOC')
    assert all(f'- {c}:' in p for c in ('acquisition', 'divestment', 'merger_demerger', 'legal_regulatory',
                                        'financial_results', 'default', 'insolvency', 'management_change', 'dividend'))
    assert 'deal_or_dispute' not in p and p.index('- legal_regulatory') < p.index('- routine')
    assert ar.validate({'category': 'acquisition'}, 'DOC')[0] == 'acquisition'
    assert ar.validate({'category': 'deal_or_dispute'}, 'DOC')[0] == 'deal_or_dispute'   # older reads


def test_live_collect_surfaces_bse_report_warnings(monkeypatch):
    import collectors.bse.announcements as bann
    import collectors.bse.client as bse_client
    import collectors.nse_events.announcements as nann
    import collectors.nse_events.client as nse_client
    import insiders_clean.raw_store as raw_store

    class Client:
        def __init__(self, *args, **kwargs):
            pass
        def close(self):
            pass

    monkeypatch.setattr(nann, 'run', lambda *args, **kwargs: {})
    monkeypatch.setattr(bann, 'run', lambda *args, **kwargs: {
        'days': [{'day': '2026-10-14'}],
        'notes': ['BSE refused (HTTP 403); stopped, what was fetched is kept'],
    })
    monkeypatch.setattr(bse_client, 'BSEClient', Client)
    monkeypatch.setattr(nse_client, 'NSEClient', Client)
    monkeypatch.setattr(raw_store, 'RawStore', lambda *args, **kwargs: object())
    monkeypatch.setattr(ar, 'load_archive', lambda *args, **kwargs: pd.DataFrame())

    notes = []
    ar.collect(object(), date(2026, 10, 14), False, notes)
    assert any('BSE collect: BSE refused' in note for note in notes)



def test_usage_can_record_only_attempts_since_a_batch_offset():
    class Client:
        attempts = [
            ('gemini-3.1-flash-lite', 200, 3.0),
            ('gemini-3.1-flash-lite', 'error', 1.0),
            ('gemini-3.1-flash-lite', 200, 5.0),
        ]

    report = ar.usage({'gemini': Client()}, {}, {'gemini': 1})
    model = report['models']['gemini:gemini-3.1-flash-lite']
    assert model['calls'] == 2
    assert model['by_status'] == {'error': 1, '200': 1}
    assert model['median_seconds_ok'] == 5.0



def test_gemini_rate_limit_is_logged_per_http_attempt_and_not_retried():
    class Response:
        status_code = 429
        text = '{"error":{"message":"quota exceeded"}}'

    class Session:
        def __init__(self):
            self.headers = {}
            self.calls = 0
        def post(self, *args, **kwargs):
            self.calls += 1
            return Response()

    session = Session()
    client = ar.GeminiCalls('test-key', session=session, sleep=lambda _: None)
    with pytest.raises(RuntimeError, match='HTTP 429'):
        client.generate(['gemini-3.1-flash-lite'], 'prompt', 'read', True)
    assert session.calls == 1
    assert len(client.attempts) == 1
    assert client.attempts[0][0:2] == ('gemini-3.1-flash-lite', 429)


def test_openai_compatible_rate_limit_is_logged_and_not_retried():
    class Response:
        status_code = 429
        text = '{"error":{"message":"rate limit"}}'

    class Session:
        def __init__(self):
            self.headers = {}
            self.calls = 0
        def post(self, *args, **kwargs):
            self.calls += 1
            return Response()

    session = Session()
    client = ar.s.OpenAICompat('groq', 'https://example.test', 'test-key',
                               session=session, sleep=lambda _: None)
    with pytest.raises(RuntimeError, match='HTTP 429'):
        client.generate(['qwen/qwen3.8-27b'], 'prompt', 'read', True)
    assert session.calls == 1
    assert len(client.attempts) == 1 and client.attempts[0][1] == 429


def test_candidates_pairs_xbrl_attachment_even_when_subject_is_not_labelled_xbrl():
    rows = pd.DataFrame([
        {'event_id': 'pdf:unlabelled', 'symbol': 'X', 'isin': 'INE000A01000', 'company': 'X Ltd',
         'subject': 'Financial Results', 'text': 'Results announcement',
         'file_url': 'https://nsearchives.nseindia.com/corporate/X_results.pdf',
         'file_type': 'pdf', 'has_xbrl': True, 'broadcast_at': '2026-10-14T10:00:00+05:30',
         'broadcast_date': '2026-10-14', 'market': 'equities'},
        {'event_id': 'attachment:unlabelled', 'symbol': 'X', 'isin': 'INE000A01000', 'company': 'X Ltd',
         'subject': 'Financial Results', 'text': 'Structured filing',
         'file_url': 'https://nsearchives.nseindia.com/corporate/xbrl/X_results.xml',
         'file_type': 'xml', 'has_xbrl': False, 'broadcast_at': '2026-10-14T10:02:00+05:30',
         'broadcast_date': '2026-10-14', 'market': 'equities'},
    ])
    out = ar.candidates(rows, pd.DataFrame(), None).set_index('event_id')
    assert out.loc['pdf:unlabelled', 'content_url'].endswith('X_results.xml')
    assert out.loc['pdf:unlabelled', 'xbrl_source_event_id'] == 'attachment:unlabelled'
    assert out.loc['attachment:unlabelled', 'group'] == 'routine'




def test_dedicated_xbrl_provenance_allows_subject_mismatch_only_when_filing_id_matches():
    rows = pd.DataFrame([
        {'event_id': 'nse:pdf:litigation', 'symbol': 'BHARATCOAL', 'isin': 'INE05XR01022',
         'company': 'Bharat Coking Coal Limited',
         'subject': 'Pendency of Litigation(s)/dispute(s) or the outcome impacting the Company',
         'text': 'Litigation disclosure',
         'file_url': 'https://nsearchives.nseindia.com/corporate/BCCL_ROID_100383_KMP_Doc.pdf',
         'file_type': 'pdf', 'has_xbrl': True, 'broadcast_at': '2026-10-14T16:41:07+05:30',
         'broadcast_date': '2026-10-14', 'market': 'equities'},
        {'event_id': 'nse:xbrl:equities:100383:abc123', 'symbol': 'BHARATCOAL', 'isin': 'INE05XR01022',
         'company': 'Bharat Coking Coal Limited', 'subject': 'Change in Directors/KMP/SMP/Auditor/RTA',
         'text': 'XBRL companion metadata',
         'file_url': 'https://nsearchives.nseindia.com/corporate/BCCL_ROID_100383_KMP_Doc.zip',
         'file_type': 'xbrl', 'has_xbrl': True, 'xbrl_url': 'https://nsearchives.nseindia.com/corporate/BCCL_ROID_100383_KMP_Doc.zip',
         'broadcast_at': '2026-10-14T16:41:07+05:30', 'broadcast_date': '2026-10-14',
         'market': 'equities'},
    ])
    out = ar.candidates(rows, pd.DataFrame(), None).set_index('event_id')
    pdf = out.loc['nse:pdf:litigation']
    xbrl = out.loc['nse:xbrl:equities:100383:abc123']
    assert pdf['content_url'].endswith('BCCL_ROID_100383_KMP_Doc.zip')
    assert pdf['xbrl_source_event_id'] == xbrl.name
    assert xbrl['group'] == 'routine'


def test_dedicated_xbrl_does_not_pair_mismatched_subject_by_date_alone():
    rows = pd.DataFrame([
        {'event_id': 'nse:pdf:litigation', 'symbol': 'X', 'isin': 'INE000A01000',
         'company': 'X Ltd', 'subject': 'Pendency of Litigation(s)/dispute(s)',
         'text': 'Litigation disclosure', 'file_url': 'https://nsearchives.nseindia.com/corporate/X_litigation.pdf',
         'file_type': 'pdf', 'has_xbrl': True, 'broadcast_at': '2026-10-14T10:00:00+05:30',
         'broadcast_date': '2026-10-14', 'market': 'equities'},
        {'event_id': 'nse:xbrl:equities:100999:abc123', 'symbol': 'X', 'isin': 'INE000A01000',
         'company': 'X Ltd', 'subject': 'Change in Directors/KMP/SMP/Auditor/RTA',
         'text': 'XBRL metadata', 'file_url': 'https://nsearchives.nseindia.com/corporate/xbrl/CIM_123.xml',
         'file_type': 'xbrl', 'has_xbrl': True, 'xbrl_url': 'https://nsearchives.nseindia.com/corporate/xbrl/CIM_123.xml',
         'broadcast_at': '2026-10-14T10:01:00+05:30', 'broadcast_date': '2026-10-14',
         'market': 'equities'},
    ])
    out = ar.candidates(rows, pd.DataFrame(), None).set_index('event_id')
    pdf = out.loc['nse:pdf:litigation']
    assert pdf['content_url'].endswith('X_litigation.pdf')
    assert pd.isna(pdf['xbrl_source_event_id'])


def test_dedicated_xbrl_feed_row_is_used_as_fast_path_without_duplicate_candidate():
    rows = pd.DataFrame([
        {'event_id': 'nse:pdf:1', 'symbol': 'MARATHON', 'isin': 'INE182D01010',
         'company': 'Marathon Nextgen Realty Limited', 'subject': 'Outcome of Board Meeting',
         'text': 'Board outcome', 'file_url': 'https://nsearchives.nseindia.com/corporate/MARATHON_outcome.pdf',
         'file_type': 'pdf', 'has_xbrl': True, 'xbrl_url': None,
         'broadcast_at': '2026-10-15T10:00:00+05:30', 'broadcast_date': '2026-10-15',
         'market': 'equities'},
        {'event_id': 'nse:xbrl:equities:APP-123:abc123', 'symbol': 'MARATHON', 'isin': None,
         'company': 'Marathon Nextgen Realty Limited', 'subject': 'Outcome of Board Meeting',
         'text': 'Outcome of Board Meeting', 'file_url': 'https://nsearchives.nseindia.com/corporate/xbrl/MARATHON_123.xml',
         'file_type': 'xml', 'has_xbrl': True,
         'xbrl_url': 'https://nsearchives.nseindia.com/corporate/xbrl/MARATHON_123.xml',
         'broadcast_at': '2026-10-15T10:00:00+05:30', 'broadcast_date': '2026-10-15',
         'market': 'equities'},
    ])
    class Master:
        market_cap_as_of = '2026-10-14'
        def resolve(self, exchange, symbol):
            return ('INE182D01010', 'exchange_symbol') if exchange == 'nse' and symbol == 'MARATHON' else None
        def record(self, isin):
            return {'market_cap': 2_000_000_000} if isin == 'INE182D01010' else None

    out = ar.candidates(rows, pd.DataFrame(), Master()).set_index('event_id')
    pdf = out.loc['nse:pdf:1']
    xbrl = out.loc['nse:xbrl:equities:APP-123:abc123']
    assert pdf['content_url'].endswith('MARATHON_123.xml')
    assert pdf['xbrl_source_event_id'] == xbrl.name
    assert xbrl['group'] == 'routine'  # companion is not a second user-facing card
    assert pd.isna(xbrl['xbrl_source_event_id'])  # do not count the companion as self-paired


def test_candidates_pair_observed_xbrl_even_when_upstream_flag_is_false():
    rows = pd.DataFrame([
        {'event_id': 'pdf:false-flag', 'symbol': 'X', 'isin': 'INE000A01000', 'company': 'X Ltd',
         'subject': 'Financial Results', 'text': 'Results announcement',
         'file_url': 'https://nsearchives.nseindia.com/corporate/X_results.pdf',
         'file_type': 'pdf', 'has_xbrl': False, 'broadcast_at': '2026-10-14T10:00:00+05:30',
         'broadcast_date': '2026-10-14', 'market': 'equities'},
        {'event_id': 'xml:false-flag', 'symbol': 'X', 'isin': 'INE000A01000', 'company': 'X Ltd',
         'subject': 'Financial Results', 'text': 'Structured filing',
         'file_url': 'https://nsearchives.nseindia.com/corporate/X_results.xml',
         'file_type': 'xml', 'has_xbrl': False, 'broadcast_at': '2026-10-14T10:02:00+05:30',
         'broadcast_date': '2026-10-14', 'market': 'equities'},
    ])
    out = ar.candidates(rows, pd.DataFrame(), None).set_index('event_id')
    assert out.loc['pdf:false-flag', 'content_url'].endswith('X_results.xml')
    assert out.loc['pdf:false-flag', 'xbrl_source_event_id'] == 'xml:false-flag'


def test_xbrl_audit_counts_structured_attachments_without_subject_label():
    cands = pd.DataFrame([
        {'event_id': 'pdf:1', 'exchange': 'NSE', 'symbol': 'X', 'isin': 'INE000A01000',
         'subject': 'Financial Results', 'broadcast_date': '2026-10-14', 'file_type': 'pdf',
         'has_xbrl': True, 'file_url': 'https://nsearchives.nseindia.com/corporate/X.pdf',
         'xbrl_url': None, 'content_url': 'https://nsearchives.nseindia.com/corporate/X.pdf',
         'xbrl_source_event_id': None, 'xbrl_source_url': None},
        {'event_id': 'xml:1', 'exchange': 'NSE', 'symbol': 'X', 'isin': 'INE000A01000',
         'subject': 'Financial Results', 'broadcast_date': '2026-10-14', 'file_type': 'xml',
         'has_xbrl': False, 'file_url': 'https://nsearchives.nseindia.com/corporate/X.xml',
         'xbrl_url': None, 'content_url': 'https://nsearchives.nseindia.com/corporate/X.xml',
         'xbrl_source_event_id': None, 'xbrl_source_url': None},
        {'event_id': 'zip:generic', 'exchange': 'NSE', 'symbol': 'X', 'isin': 'INE000A01000',
         'subject': 'Investor Presentation', 'broadcast_date': '2026-10-14', 'file_type': 'zip',
         'has_xbrl': False, 'file_url': 'https://nsearchives.nseindia.com/corporate/X_presentation.zip',
         'xbrl_url': None, 'content_url': 'https://nsearchives.nseindia.com/corporate/X_presentation.zip',
         'xbrl_source_event_id': None, 'xbrl_source_url': None},
    ])
    audit = ar.xbrl_audit(cands)
    assert audit['candidates'] == 3
    assert audit['has_xbrl_flagged'] == 1
    assert audit['has_xbrl_flagged_pdf_rows'] == 1
    assert audit['flagged_without_direct_xbrl_url'] == 1
    assert audit['structured_attachments'] == 1
    assert audit['zip_attachments'] == 1  # generic ZIP is an archive, not proof of XBRL
    assert audit['xbrl_labelled_zip_attachments'] == 0
    assert audit['xbrl_attachments'] == 1  # XML format is a positive signal without a subject label
    assert audit['xbrl_subject_labels'] == 0
    assert len(audit['zip_samples']) == 1
    assert audit['zip_samples'][0]['event_id'] == 'zip:generic'


def test_candidates_do_not_pair_unlabelled_unrelated_zip_without_exact_subject():
    rows = pd.DataFrame([
        {'event_id': 'pdf:1', 'symbol': 'X', 'isin': 'INE000A01000', 'company': 'X Ltd',
         'subject': 'Financial Results', 'text': 'Results announcement',
         'file_url': 'https://nsearchives.nseindia.com/corporate/X_results.pdf',
         'file_type': 'pdf', 'has_xbrl': True, 'broadcast_at': '2026-10-14T10:00:00+05:30',
         'broadcast_date': '2026-10-14', 'market': 'equities'},
        {'event_id': 'zip:unrelated', 'symbol': 'X', 'isin': 'INE000A01000', 'company': 'X Ltd',
         'subject': 'Investor presentation', 'text': 'Presentation attachment',
         'file_url': 'https://nsearchives.nseindia.com/corporate/X_presentation.zip',
         'file_type': 'zip', 'has_xbrl': False, 'broadcast_at': '2026-10-14T10:02:00+05:30',
         'broadcast_date': '2026-10-14', 'market': 'equities'},
    ])
    out = ar.candidates(rows, pd.DataFrame(), None).set_index('event_id')
    assert out.loc['pdf:1', 'content_url'].endswith('X_results.pdf')
    assert pd.isna(out.loc['pdf:1', 'xbrl_source_event_id'])


def _ledger_store(monkeypatch):
    import clean_writer
    store = {}
    monkeypatch.setattr(clean_writer, 'get', lambda r2, key: store.get(key))
    monkeypatch.setattr(clean_writer, 'put', lambda r2, key, body, content_type=None: store.__setitem__(key, body))
    monkeypatch.setattr(clean_writer, 'list_keys', lambda r2, prefix: sorted(k for k in store if k.startswith(prefix)))
    return store


def test_usage_ledger_replaces_its_own_file_so_no_call_counts_twice(monkeypatch):
    store = _ledger_store(monkeypatch)
    c = FakeClient(['{}', '{}', '{}'])
    lanes = {'main': ar.Lane('main', ['nvidia:m'], {'nvidia': c})}
    ledger = ar.UsageLedger(object(), '2026-10-15', {'nvidia': c}, lanes, 'live')
    c.generate(['m'], 'p', 'read', True)
    assert ledger.write()
    c.generate(['m'], 'p', 'read', True)
    c.generate(['m'], 'p', 'read', True)
    assert ledger.write() and not ledger.write()        # unchanged total: nothing to write
    runs = [k for k in store if '/runs/' in k]
    saved = json.loads(store[ledger.key])
    assert runs == [ledger.key] and saved['usage']['models']['nvidia:m']['calls'] == 3
    assert sum(saved['calls_by_minute']['nvidia:m'].values()) == 3
    now = datetime.now(timezone.utc)
    assert ar.used_today(object(), now) == {'nvidia:m': 3}
    assert ar.used_today(object(), now, skip_run=ledger.run_id) == {}


def _run_file(store, day, run, minutes):
    store[f'clean/reports/announcement_reader/{day}/runs/{run}.json'] = json.dumps(
        {'calls_by_minute': minutes}).encode()


def test_each_provider_counts_its_own_day(monkeypatch):
    store = _ledger_store(monkeypatch)
    # 15 Oct 2026 14:00 IST = 08:30 UTC; Pacific midnight (PDT) = 07:00 UTC, so Gemini's day began 1.5 h ago.
    now = datetime(2026, 10, 15, 8, 30, tzinfo=timezone.utc)
    _run_file(store, '2026-10-15', 'a', {
        'gemini:g': {'2026-10-15T06:59Z': 5, '2026-10-15T07:01Z': 2},   # before / after Pacific midnight
        'groq:q': {'2026-10-15T06:59Z': 5, '2026-10-15T07:01Z': 2}})    # both inside the last 24 hours
    _run_file(store, '2026-10-14', 'b', {
        'groq:q': {'2026-10-14T08:29Z': 7, '2026-10-14T08:31Z': 3},      # 24 h and 1 min / 23 h 59 min ago
        'nvidia:n': {'2026-10-14T20:00Z': 4}})
    store['clean/reports/announcement_reader/2026-10-15.json'] = json.dumps(   # before 15 Oct: no minutes
        {'runs': [{'at': '2026-10-15T07:30:00+00:00', 'usage': {'models': {'gemini:g': {'calls': 1}}}},
                  {'at': '2026-10-15T06:30:00+00:00', 'usage': {'models': {'gemini:g': {'calls': 9}}}}]}).encode()
    _run_file(store, '2026-10-13', 'old', {'nvidia:n': {'2026-10-13T20:00Z': 50}})   # not read
    assert ar.used_today(object(), now) == {'gemini:g': 3, 'groq:q': 10, 'nvidia:n': 4}


def test_gemini_day_follows_pacific_daylight_saving():
    winter = datetime(2026, 12, 15, 12, 0, tzinfo=timezone.utc)
    summer = datetime(2026, 7, 15, 12, 0, tzinfo=timezone.utc)
    assert ar.window_start('gemini', winter) == datetime(2026, 12, 15, 8, 0, tzinfo=timezone.utc)
    assert ar.window_start('gemini', summer) == datetime(2026, 7, 15, 7, 0, tzinfo=timezone.utc)
    assert ar.window_start('nvidia', summer) == datetime(2026, 7, 14, 12, 0, tzinfo=timezone.utc)


def test_usage_ledger_has_counted_calls_before_a_run_is_cut_off(monkeypatch):
    import time as _time
    store = _ledger_store(monkeypatch)
    c = FakeClient(['{}', '{}'])
    ledger = ar.UsageLedger(object(), '2026-10-15', {'nvidia': c}, {}, 'live', every=0.01).start()
    c.generate(['m'], 'p', 'read', True)
    c.generate(['m'], 'p', 'read', True)
    deadline = _time.monotonic() + 5
    while ledger.written_calls != 2 and _time.monotonic() < deadline:
        _time.sleep(0.01)
    ledger._stop.set()                                   # cancelled: close() never runs
    assert json.loads(store[ledger.key])['usage']['models']['nvidia:m']['calls'] == 2


def test_usage_ledger_write_failure_is_retried_not_raised(monkeypatch):
    import clean_writer
    store = _ledger_store(monkeypatch)
    c = FakeClient(['{}'])
    c.generate(['m'], 'p', 'read', True)
    ledger = ar.UsageLedger(object(), '2026-10-15', {'nvidia': c}, {}, 'dry_run')

    def down(r2, key, body, content_type=None):
        raise ConnectionError('R2 down')
    monkeypatch.setattr(clean_writer, 'put', down)
    assert not ledger.write()
    monkeypatch.setattr(clean_writer, 'put', lambda r2, key, body, content_type=None: store.__setitem__(key, body))
    assert ledger.close(counts={'candidates': 1})
    saved = json.loads(store[ledger.key])
    assert saved['source'] == 'dry_run' and saved['counts'] == {'candidates': 1}
    assert saved['usage']['models']['nvidia:m']['calls'] == 1


def test_daily_limit_counts_calls_recorded_by_earlier_runs(monkeypatch):
    store = _ledger_store(monkeypatch)
    monkeypatch.setitem(ar.DAILY_CALLS, 'groq:q', 100)
    now = datetime(2026, 10, 15, 8, 30, tzinfo=timezone.utc)
    _run_file(store, '2026-10-15', '7-1-dry_run-c', {'groq:q': {'2026-10-15T08:00Z': 95}})
    lane = ar.Lane('groq', ['groq:q'], {'groq': FakeClient([])})
    lane.used_today = ar.used_today(object(), now)
    assert lane.models() == []                           # 95% of the day's 100 already used


class _Resp:
    def __init__(self, status, body=b''):
        self.status_code, self.content, self.ok = status, body, status < 400

    def raise_for_status(self):
        if not self.ok:
            raise RuntimeError(f'HTTP {self.status_code}')


class _Session:
    def __init__(self, answers):
        self.answers, self.asked = answers, []

    def get(self, url, **_):
        self.asked.append(url)
        return self.answers[url]


def test_bse_download_falls_back_to_attachhis_when_attachlive_is_gone():
    live = 'https://www.bseindia.com/xml-data/corpfiling/AttachLive/a.pdf'
    his = live.replace('AttachLive', 'AttachHis')
    session = _Session({live: _Resp(404, b'<html>'), his: _Resp(200, b'%PDF-1.4')})
    assert sample.download(live, session) == b'%PDF-1.4'
    assert session.asked == [live, his]


def test_bse_download_uses_attachlive_when_it_works_and_nse_never_falls_back():
    live = 'https://www.bseindia.com/xml-data/corpfiling/AttachLive/a.pdf'
    session = _Session({live: _Resp(200, b'%PDF')})
    assert sample.download(live, session) == b'%PDF' and session.asked == [live]
    nse = 'https://nsearchives.nseindia.com/corporate/X.pdf'
    session = _Session({nse: _Resp(404)})
    try:
        sample.download(nse, session)
    except RuntimeError:
        pass
    else:
        raise AssertionError('a missing NSE file must raise')
    assert session.asked == [nse]


def test_bse_download_raises_the_first_error_when_both_paths_are_gone():
    live = 'https://www.bseindia.com/xml-data/corpfiling/AttachLive/a.pdf'
    session = _Session({live: _Resp(404), live.replace('AttachLive', 'AttachHis'): _Resp(404)})
    try:
        sample.download(live, session)
    except RuntimeError as exc:
        assert '404' in str(exc)
    else:
        raise AssertionError('both paths missing must raise')


def test_a_filing_in_the_text_cache_is_read_without_a_download():
    asked = []

    def cache(row):
        asked.append(row['event_id'])
        return {'text': DOC, 'notes': '0.1 MB', 'file_sha256': 'f' * 64, 'status': 'ok'} if row['event_id'] == 'nse:1' else None

    def fetch(url):
        assert 'nse:1' not in url, 'a cached filing must not be downloaded'
        return b'one'

    client = FakeClient([QIP, QIP])
    lanes = {'nvidia': ar.Lane('nvidia', ['nvidia:m'], {'nvidia': client})}
    rows, _ = ar.run(_qips(2), lanes, None, 600, fetch=fetch, idle_wait=0.01, text_cache=cache,
                     max_filings=2)
    by = {r['event_id']: r for r in rows}
    assert sorted(asked) == ['nse:1', 'nse:2']
    assert by['nse:1']['status'] == 'read' and by['nse:1']['file_sha256'] == 'f' * 64
    assert by['nse:1']['source_format'] == 'pdf' and by['nse:1']['text_chars'] == len(DOC)


def test_a_document_longer_than_the_reader_limit_is_held_back_not_read_in_part(monkeypatch):
    monkeypatch.setattr(ar.s, 'text_of', lambda data: (DOC, ['0.1 MB', 'cut to 300,000 of 450,000 characters']))
    client = FakeClient([QIP])
    lanes = {'nvidia': ar.Lane('nvidia', ['nvidia:m'], {'nvidia': client})}
    rows, _ = ar.run(_qips(1), lanes, None, 600, fetch=lambda u: u.encode(), idle_wait=0.01, max_filings=1)
    assert rows[0]['status'] == 'not_read' and 'not read in part' in rows[0]['reason'] and 'cut to' in rows[0]['reason']
    assert client.asked == []   # no model was asked
    done = pd.DataFrame(rows)
    assert ar.choose(_qips(1), done, date(2026, 10, 13))[0].empty   # final until long documents are read by section


def test_a_cached_document_over_the_limit_is_held_back_the_same_way(monkeypatch):
    monkeypatch.setattr(ar.s, 'MAX_CHARS', 20)
    cache = lambda row: {'text': DOC, 'notes': '0.1 MB', 'file_sha256': 'a' * 64, 'status': 'ok'}   # noqa: E731
    client = FakeClient([QIP])
    lanes = {'nvidia': ar.Lane('nvidia', ['nvidia:m'], {'nvidia': client})}
    rows, _ = ar.run(_qips(1), lanes, None, 600, fetch=lambda u: 1 / 0, idle_wait=0.01, text_cache=cache, max_filings=1)
    assert rows[0]['status'] == 'not_read' and 'cut to 20 of' in rows[0]['reason'] and client.asked == []


def test_a_cached_empty_file_is_no_text_without_a_download():
    cache = lambda row: {'text': '', 'notes': 'no text layer (scanned?)', 'file_sha256': 'b' * 64, 'status': 'no_text'}   # noqa: E731
    lanes = {'nvidia': ar.Lane('nvidia', ['nvidia:m'], {'nvidia': FakeClient([])})}
    rows, _ = ar.run(_qips(1), lanes, None, 600, fetch=lambda u: 1 / 0, idle_wait=0.01, text_cache=cache, max_filings=1)
    assert rows[0]['status'] == 'no_text' and 'no text layer' in rows[0]['reason']
