"""The announcement-reader sample check (scripts/announcement_sample.py):
its quote and number checks and scoring, with no network and no model."""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import announcement_sample as a

DOC = ('the Board has approved the proposal for buy-back of up to 14,75,000 (Fourteen Lakh Seventy Five\n'
       'Thousand) fully paid-up equity shares ... at a price of ₹162/- (Rupees One Hundred Sixty Two only)')
ROW = {'symbol': 'GLOBAL', 'subject': 'Buyback',
       'expected': {'category': 'buyback_tender', 'price_per_share': 162, 'shares': 1475000}}


def test_quotes_must_be_in_the_document_and_hold_the_number():
    assert a.quote_found('buy-back of up to 14,75,000 (Fourteen Lakh Seventy Five Thousand)', DOC)  # across a line break
    assert not a.quote_found('buy-back of up to 15,00,000 shares', DOC)
    assert not a.quote_found('162', DOC)   # too short to prove anything
    assert a.digits_in_quote(1475000, 'up to 14,75,000 (Fourteen Lakh') and a.digits_in_quote(475, '₹475.00/-')
    assert not a.digits_in_quote(1475000, 'up to 14,75 shares')


def test_a_right_value_with_an_invented_quote_does_not_score():
    out = {'category': 'buyback_tender', 'fields': [
        {'name': 'price_per_share', 'value': 162, 'quote': 'at a price of ₹162/- (Rupees One Hundred Sixty Two only)'},
        {'name': 'shares', 'value': 1475000, 'quote': 'buy-back of 14,75,000 shares in total'},   # not in DOC
        {'name': 'amount', 'value': 1, 'quote': 'nowhere in the filing'}]}
    c = a.check(ROW, {'category': 'buyback_open_market', 'read_pdf': True}, out, DOC)
    assert c['score'] == [2, 3] and not c['sort_category_right']
    extra = next(f for f in c['fields'] if f['field'] == 'amount')
    assert extra['match'] is None and extra['quote_found'] is False
    assert '| gemini | **2 of 3** | 2 |' in a.report_markdown([c], {'read': 'r', 'sort': 's'})   # 2 held back


def test_values_compare_as_filed_numbers_flags_and_ratios():
    assert a.same('amount', 2999999852.45, '2,99,99,99,852.45') and not a.same('shares', 150000, 15000)
    assert a.same('allottee_is_promoter', True, 'true') and a.same('entity', 'subsidiary', 'Subsidiary')
    assert a.in_units('28,200.00', 'Lakhs') == 2_820_000_000 and a.in_units('3,351', 'Million') == 3_351_000_000
    assert a.same('capacity_to', '240 KL per day', '240 KL per day')


def test_amounts_are_converted_by_our_code_and_metrics_found_by_value():
    doc = ('the consolidated orders received by the Company are worth Rs. 102 Cr out of which ... '
           'Investment Required Indian Rupees 3,351 Million')
    row = {'symbol': 'X', 'subject': 's', 'expected': {'category': 'capex', 'amount': 3_351_000_000,
                                                       'metrics': [{'label': 'order intake', 'value': 1_020_000_000}]}}
    out = {'category': 'capex', 'fields': [
        {'name': 'amount', 'value': '3,351', 'quote': 'Investment Required Indian Rupees 3,351 Million'},
        {'name': 'amount_unit', 'value': 'million', 'quote': 'Indian Rupees 3,351 Million'}],
        'metrics': [{'label': 'orders received', 'period': 'Sep 2026', 'value': 102, 'unit': 'Cr',
                     'quote': 'orders received by the Company are worth Rs. 102 Cr'}]}
    c = a.check(row, None, out, doc)
    assert c['score'] == [3, 3]
    assert a.same('ratio', '2:21', '2 : 21') and a.parse_json('```json\n{"category": "qip"}\n```') == {'category': 'qip'}
    assert a.parse_json('no json here') is None



def test_a_unit_must_not_multiply_a_number_written_in_full():
    # 13 Oct: two amounts from one reader passed the quote and digit checks with "crore" as their unit
    q = ('Rs. 299,99,99,852.45 (Rupees Two Hundred Ninety-Nine Crore Ninety-Nine Lakh Ninety-Nine Thousand '
         'Eight Hundred Fifty-Two and Paise Forty-Five only)')
    assert a.unit_backed('299,99,99,852.45', 'crore', q, 'exact') is False   # crore only in the words
    assert a.unit_backed('95,00,00,000', 'crore', 'Size of Issue: INR 95,00,00,000', 'table') is False
    assert a.unit_backed('299,99,99,852.45', 'rupees', q, 'exact') is None
    assert a.unit_backed('28,200.00', 'lakh', 'not exceeding ₹ 28,200.00 Lakhs (Rupees', 'exact') is True
    assert a.unit_backed('102', 'Cr', 'worth Rs. 102 Cr. out of which', 'exact') is True
    assert a.unit_backed('200.00', 'crore', 'Total 200.00', 'table') is True   # unit in the column heading
    assert a.unit_backed('200.00', 'crore', 'Total 200.00 and 5 crore', 'exact') is False
    row = {'symbol': 'X', 'subject': 's', 'expected': {'category': 'qip', 'amount': 2_999_999_852.45}}
    out = {'category': 'qip', 'fields': [{'name': 'amount', 'value': '299,99,99,852.45', 'quote': q},
                                         {'name': 'amount_unit', 'value': 'crore', 'quote': q}]}
    f = next(x for x in a.check(row, None, out, q)['fields'] if x['field'] == 'amount')
    assert f['unit_backed'] is False and f['match'] is False



def test_dates_compare_as_dates_whatever_the_writing():
    for written in ('October 1, 2026', '1st October, 2026', '01.10.2026', '01/10/2026', '1-Oct-2026', '2026-10-01'):
        assert a.same('record_date', '2026-10-01', written), written
    assert not a.same('record_date', '2026-10-01', 'September 30, 2026') and not a.same('record_date', '2026-10-01', 'soon')


def test_sample_file_lists_real_filings_with_their_links():
    rows = json.loads((Path(a.HERE) / 'announcement_sample_expected.json').read_text(encoding='utf-8'))
    assert len(rows) == 24 and len({r["seq_id"] for r in rows}) == 24
    assert all(r['file_url'].startswith('https://nsearchives.nseindia.com/corporate/') for r in rows)
    assert all(r['expected']['category'] in a.CATEGORIES for r in rows)
    assert all(set(r['expected']) - {'category', 'metrics'} <= set(a.FIELDS) for r in rows)


class _Resp:
    def __init__(self, status, body=None):
        self.status_code, self._body, self.text = status, body or {}, json.dumps(body or {})

    def json(self):
        return self._body


class _Session:
    def __init__(self, answers):
        self.answers, self.asked, self.headers = list(answers), [], {}

    def post(self, url, **kw):
        self.asked.append(url.split('/models/')[1].split(':')[0] if '/models/' in url else kw['json']['model'])
        return self.answers.pop(0)


def test_a_busy_model_hands_over_to_the_next_at_once():
    ok = _Resp(200, {'candidates': [{'content': {'parts': [{'text': '{"category": "qip"}'}]}}],
                     'usageMetadata': {'promptTokenCount': 12}})
    s = _Session([_Resp(503), ok])
    g = a.Gemini('k', session=s, sleep=lambda _: None)
    text, usage, used = g.generate(['gemini-3.5-flash-lite', 'gemini-3.1-flash-lite'], 'p', 'read', True)
    assert (text, usage['promptTokenCount']) == ('{"category": "qip"}', 12)
    assert used == 'gemini-3.1-flash-lite' and s.asked == ['gemini-3.5-flash-lite', 'gemini-3.1-flash-lite']
    s = _Session([_Resp(503), _Resp(500), _Resp(503), _Resp(429)])
    try:
        a.Gemini('k', session=s, sleep=lambda _: None).generate(['m1', 'm2'], 'p', 'read', True)
        raise AssertionError('should have given up')
    except RuntimeError as exc:
        assert 'busy' in str(exc) and len(s.asked) == 4   # two rounds over both models


def test_other_providers_answer_in_the_openai_form_and_readers_come_from_the_run_file():
    body = {'choices': [{'message': {'content': '<think>{x}</think>{"category": "rights"}'}}],
            'usage': {'prompt_tokens': 900}}
    s = _Session([_Resp(429), _Resp(200, body)])
    c = a.OpenAICompat('groq', 'https://x/v1', 'k', session=s, sleep=lambda _: None)
    text, usage, used = c.generate(['openai/gpt-oss-120b', 'qwen/qwen3.8-27b'], 'p', 'read', True)
    assert (a.parse_json(text), usage['promptTokenCount'], used) == ({'category': 'rights'}, 900, 'qwen/qwen3.8-27b')
    assert a.parse_readers('# x\nGLOBAL\nreaders: gemini, groq:openai/gpt-oss-120b\n') == [
        'gemini', 'groq:openai/gpt-oss-120b']
    assert a.parse_readers('GLOBAL') == ['gemini']


def test_parallel_jobs_combine_into_one_report(tmp_path, capsys):
    rows = {'groq:openai/gpt-oss-120b': {'score': [3, 3], 'seconds': 8.0},
            'nvidia:nvidia/nemotron-3-super-120b-a12b': {'error': 'RuntimeError: busy'}}
    for i, (rd, extra) in enumerate(rows.items()):
        (tmp_path / f'job{i}').mkdir()
        (tmp_path / f'job{i}' / 'announcement_sample_results.json').write_text(json.dumps(
            {'models': {'sort': 'gemma' if i else ''}, 'results': [{'symbol': 'GLOBAL', 'subject': 's',
                                                                    'reader': rd, **extra}]}))
    a.main(['--combine', str(tmp_path)])
    out = capsys.readouterr().out
    assert '| GLOBAL | 3/3 | error: RuntimeError: busy |' in out and 'Sorter `gemma`' in out


def test_one_job_per_reader_and_only_gemini_sorts():
    jobs = a.matrix('GLOBAL\nreaders: gemini, nvidia:z-ai/glm-5.3\n')
    assert jobs == [{'slug': 'gemini', 'reader': 'gemini', 'flags': ''},
                    {'slug': 'nvidia-z-ai-glm-5.3', 'reader': 'nvidia:z-ai/glm-5.3', 'flags': '--no-sort'}]
    assert len(a.matrix('# all')) == len(a.DEFAULT_READERS.split(','))
    assert a.matrix('readers: zai:glm-4.7-flash, zai:glm-4.7-flash+thinking') == [
        {'slug': 'zai-glm-4.7-flash-zai-glm-4.7-flash-thinking', 'reader': 'zai:glm-4.7-flash, zai:glm-4.7-flash+thinking',
         'flags': '--no-sort'}]


def test_zai_thinking_is_switched_by_the_readers_line():
    body = {'choices': [{'message': {'content': '{"category": "rights"}'}}], 'usage': {}}
    s = _Session([_Resp(200, body), _Resp(200, body)])
    sent = []
    post = s.post
    s.post = lambda url, **kw: (sent.append(kw['json']), post(url, **kw))[1]
    c = a.OpenAICompat('zai', 'https://x/v4', 'k', session=s, sleep=lambda _: None)
    c.generate(['glm-4.7-flash+thinking'], 'p', 'read', True)
    c.generate(['glm-4.7-flash'], 'p', 'read', True)
    assert [(b['model'], b['thinking']['type']) for b in sent] == [
        ('glm-4.7-flash', 'enabled'), ('glm-4.7-flash', 'disabled')]


SML = """                                  Production                              Sales                                 Export
 Particulars
                        FY 2026             FY 2027          FY 2026           FY 2027                 FY 2026         FY 2027
Commercial
                                1049            1257              812               1071                  138              53
Vehicles

You are requested to take the same on your records."""


def test_a_table_row_joined_to_its_headings_counts_as_table_not_exact():
    assert a.quote_found('Sales Commercial Vehicles FY 2027 1071', SML) == 'table'
    assert a.quote_found('Commercial Vehicles Sales FY 2027 1999', SML) is False   # number not in the table
    assert a.quote_found('Domestic Sales FY 2027 1071', SML) is False             # a word the block lacks
    assert a.quote_found('You are requested to take the same', SML) == 'exact'


def test_numbers_written_with_currency_or_unit_are_read_once_never_guessed():
    assert [a._num(v) for v in ('₹162/-', 'Rs. 29/-', 'INR 231.55/-', '1,81,10,473 Equity Shares', '-2.5%')] == [
        162, 29, 231.55, 18110473, -2.5]
    assert a._num('from ₹350 Cr to ₹600 crore') is None and a._num('nil') is None and a._num(True) is None
    assert a.digits_in_quote('₹162/-', 'at a price of ₹162/- per share')


def test_a_small_context_model_gets_a_small_reply_budget():
    body = {'choices': [{'message': {'content': '{}'}}], 'usage': {}}
    s = _Session([_Resp(200, body), _Resp(200, body)])
    sent = []
    post = s.post
    s.post = lambda url, **kw: (sent.append(kw['json']['max_tokens']), post(url, **kw))[1]
    c = a.OpenAICompat('nvidia', 'https://x/v1', 'k', session=s, sleep=lambda _: None)
    c.generate(['writer/palmyra-fin-70b-32k'], 'p', 'read', True)
    c.generate(['moonshotai/kimi-k3'], 'p', 'read', True)
    assert sent == [4096, 16384]
    assert a.PROVIDERS['zai'][0] == 'https://api.z.ai/api/paas/v4'   # keys from z.ai (owner's account)


def test_a_reply_left_in_reasoning_content_is_read_and_zai_stays_free():
    body = {'choices': [{'message': {'content': '', 'reasoning_content': '{"category": "qip"}'}}], 'usage': {}}
    c = a.OpenAICompat('nvidia', 'https://x/v1', 'k', session=_Session([_Resp(200, body)]), sleep=lambda _: None)
    assert a.parse_json(c.generate(['deepseek-ai/deepseek-v4.1-flash'], 'p', 'read', True)[0]) == {'category': 'qip'}
    assert set(a.FREE_ONLY['zai']) == {'glm-4.7-flash', 'glm-4.5-flash', 'glm-4.6v-flash'}   # Free on Z.ai's pricing page


def test_each_zai_model_gets_its_own_job_with_its_thinking_variant():
    jobs = a.matrix('readers: zai:glm-4.7-flash, zai:glm-4.7-flash+thinking, zai:glm-4.5-flash')
    assert [j['reader'] for j in jobs] == ['zai:glm-4.7-flash, zai:glm-4.7-flash+thinking', 'zai:glm-4.5-flash']
