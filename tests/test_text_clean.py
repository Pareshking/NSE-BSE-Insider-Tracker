"""The cleaning removes padding, page furniture, exchange addresses and letterhead contacts, and nothing else."""
from __future__ import annotations

import re
from collections import Counter

from insiders_clean.text_clean import clean


def nums(t):
    return Counter(re.findall(r'\d[\d,]*\.?\d*', t))


LETTER = """                         ACME LIMITED
Registered Office: 12 Mill Road, Pune 411001
CIN: L12345MH2001PLC000001        Tel: 020-1234567
E-mail: cs@acme.test      Website: www.acme.test

To,
The Manager - Listing Department
BSE Limited
Phiroze Jeejeebhoy Towers, Dalal Street
Mumbai - 400 001

Subject: Allotment of 1,81,10,473 equity shares at Rs. 165.65 per share

The Board approved the allotment on 13 October 2026.

Particulars                       FY26          FY25
Revenue from operations        1,234.50       1,100.25
Profit after tax                 210.10         180.40

For ACME LIMITED
Company Secretary
Tel: 020-1234568
"""


def test_a_letter_loses_its_padding_exchange_address_and_letterhead_but_keeps_every_number_and_sentence():
    text, removed = clean(LETTER, 'Allotment of Securities')
    assert 'Phiroze' not in text and 'Dalal Street' not in text and 'Listing Department' not in text
    assert 'CIN:' not in text and 'Registered Office' not in text and 'www.acme.test' not in text
    assert 'The Board approved the allotment on 13 October 2026.' in text
    assert 'Revenue from operations | 1,234.50 | 1,100.25' in text and 'Profit after tax | 210.10 | 180.40' in text
    assert 'Subject: Allotment of 1,81,10,473 equity shares at Rs. 165.65 per share' in text
    assert set(removed) >= {'padding', 'exchange address', 'letterhead contacts'}
    lost = nums(LETTER) - nums(text)
    assert set(lost) <= {'12', '411001', '12345', '2001', '000001', '020-1234567'.split('-')[0], '1234567', '1234568', '400', '001', '020'}
    assert nums(text)['165.65'] == 1 and nums(text)['1,81,10,473'] == 1 and nums(text)['1,234.50'] == 1


def test_a_filing_about_the_registered_office_keeps_the_office_lines():
    letter = 'Registered Office: new address 99 Lake Road, Nagpur\nThe registered office is shifted from Pune to Nagpur.\n'
    text, removed = clean(letter, 'Change in Registered Office Address')
    assert 'new address 99 Lake Road' in text and 'letterhead contacts' not in removed
    assert 'new address 99 Lake Road' not in clean(letter, 'Outcome of Board Meeting')[0]   # a letterhead, not content


def test_letterhead_lines_in_the_middle_of_a_long_document_are_content():
    body = '\n'.join(f'Line {i} of the agreement' for i in range(60))
    doc = body + '\nTel: 020-9999999 is the helpline named in clause 9\n' + body
    assert 'helpline named in clause 9' in clean(doc, 'Agreements')[0]


def test_lines_repeated_on_three_pages_and_page_numbers_go_but_a_line_on_two_pages_stays():
    pages = [f'ACME LIMITED Annual Report\nbody of page {i} with value {i}00\nPage {i} of 4' for i in range(1, 5)]
    pages[1] = pages[1].replace('\nbody', '\nOnly here and on the next page\nbody')
    pages[2] = pages[2].replace('\nbody', '\nOnly here and on the next page\nbody')
    text, removed = clean('\f'.join(pages))
    assert text.count('ACME LIMITED Annual Report') == 1 and 'Page 1 of 4' not in text and removed['page furniture'] > 0
    assert text.count('Only here and on the next page') == 2
    assert all(f'body of page {i} with value {i}00' in text for i in range(1, 5))
    two = '\f'.join(pages[:2])
    assert clean(two)[0].count('ACME LIMITED Annual Report') == 2   # under 3 pages: repeats are not judged


def test_short_documents_empty_text_and_idempotence():
    assert clean('')[0] == '' and clean(None)[0] == ''
    once, _ = clean(LETTER, 'x')
    again, removed = clean(once, 'x')
    assert again == once and not removed
    assert clean('A   B  C')[0] == 'A | B C'


def test_table_rows_that_repeat_their_labels_page_after_page_are_data_not_furniture():
    pages = [f'Segment revenue    {1000 + i}.5    {900 + i}.5\nSegment profit    {100 + i}.2    {90 + i}.2' for i in range(1, 6)]
    text, removed = clean('\f'.join(pages))
    for i in range(1, 6):
        assert f'Segment revenue | {1000 + i}.5 | {900 + i}.5' in text and f'Segment profit | {100 + i}.2 | {90 + i}.2' in text
    assert 'page furniture' not in removed


def test_a_table_header_repeated_on_every_page_is_kept_once_with_the_first_table():
    head = 'Particulars    Quarter ended 30.09.2026    Quarter ended 30.09.2025'
    pages = [f'{head}\nrow {i}    {i}00.0    {i}10.0' for i in range(1, 5)]
    text, _ = clean('\f'.join(pages))
    assert text.count('Particulars | Quarter ended 30.09.2026 | Quarter ended 30.09.2025') == 1
    assert text.index('Particulars') < text.index('row 1')


def test_identical_rows_in_the_middle_of_pages_are_kept_so_a_voting_table_stays_whole():
    row = 'Promoter    E-Voting    8188115    100.0000    8188115    0    100.0000    0.0000'
    pages = [f'Resolution {i}\nCategory  Mode  Votes\n{row}\nPublic    E-Voting    {i}00    50.0000\nResult: passed\nfooter line one\nfooter two\nfooter three'
             for i in range(1, 6)]
    text, removed = clean('\f'.join(pages))
    assert text.count('Promoter | E-Voting | 8188115 | 100.0000 | 8188115 | 0 | 100.0000 | 0.0000') == 5
    assert all(f'Public | E-Voting | {i}00 | 50.0000' in text for i in range(1, 6))


def test_an_edge_line_that_is_mostly_digits_is_data_not_furniture():
    pages = ['Annual Report\nbody one\n1234567 890123 456789', 'Annual Report\nbody two\n1234567 890123 456789',
             'Annual Report\nbody three\n1234567 890123 456789']
    text, _ = clean('\f'.join(pages))
    assert text.count('1234567 890123 456789') == 3 and text.count('Annual Report') == 1


def test_clean_with_lines_names_the_removed_lines_by_rule():
    from insiders_clean.text_clean import clean_with_lines
    _, _, lines = clean_with_lines(LETTER, 'Allotment of Securities')
    assert any('Phiroze' in x for x in lines['exchange address']) and any('CIN:' in x for x in lines['letterhead contacts'])


def test_exchange_terms_in_the_body_are_not_removed_as_letterhead():
    body = (
        "ACME LIMITED\nTo,\nThe Manager - Listing Department\nBSE Limited\n"
        "Phiroze Jeejeebhoy Towers, Dalal Street\nMumbai - 400 001\n"
        "Subject: Material litigation update\n\n"
        "The Listing Department issued an order against the company.\\n"
        "The company also leases an office on Dalal Street.\\n"
    )
    text, removed = clean(body, 'Material litigation update')
    assert 'Listing Department issued an order' in text
    assert 'leases an office on Dalal Street' in text
    assert 'Phiroze Jeejeebhoy Towers' not in text
    assert 'Listing Department' in ' '.join(removed.get('exchange address', []))
