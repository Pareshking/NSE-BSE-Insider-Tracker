"""One block deal is one row on the company page: the seller, the buyers by type, every buyer (IIFL Finance, 18 Nov 2026)."""
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'streamlit_app'))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from screens.company import deal_blocks  # noqa: E402


def _deals():
    rows = [('Fih Mauritius Investments LTD', 'SELL', 109824712)]
    rows += [('SBI Mutual Fund', 'BUY', 8153054), ('Rimco India Limited', 'BUY', 6077795), ('Nippon India Mutual Fund', 'BUY', 4457050),
             ('Tata Aig General Insurance Company Limited', 'BUY', 1215593), ('GS India Equity', 'BUY', 75945)]
    d = pd.DataFrame([{'date': '2026-11-18', 'client_name': c, 'side': s, 'quantity': q, 'price': 617.0, 'value': q * 617.0,
                       'pct_of_mcap': q / 4.268e8 * 100, 'feeds': 'block'} for c, s, q in rows])
    other = pd.DataFrame([{'date': '2026-11-10', 'client_name': 'Someone', 'side': 'BUY', 'quantity': 1000, 'price': 600.0,
                           'value': 6e5, 'pct_of_mcap': 0.0, 'feeds': 'bulk'}])
    return pd.concat([d, other], ignore_index=True)


def test_one_block_row_names_seller_and_buyers():
    blocks, rest = deal_blocks(_deals())
    assert len(blocks) == 1 and len(rest) == 1   # the lone bulk deal stays its own row
    b = blocks[0]
    assert b['what'] == 'Block deal'
    assert b['who'].startswith('Fih Mauritius') and '5 buyers' in b['who']
    assert 'sold' in b['text'] and 'SBI Mutual Fund' in b['text'] and '+2 more' in b['text']
    assert b['pct'] < 0   # a sale reads negative
    facts = dict(b['_facts'])
    assert 'Mutual fund' in facts['Buyers by type'] and 'Insurer' in facts['Buyers by type']
    assert 'Bought: GS India Equity' in facts
    assert 'of the' in facts['Buyers named']


def test_two_legs_are_not_a_block():
    d = _deals().head(2)
    blocks, rest = deal_blocks(d)
    assert blocks == [] and len(rest) == 2
