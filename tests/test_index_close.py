from insiders_clean import index_close

BODY = (b"Index Name,Index Date,Open Index Value,High Index Value,Low Index Value,Closing Index Value,Points Change,Change(%),Volume,Turnover (Rs. Cr.),P/E,P/B,Div Yield\n"
        b"Nifty 50,02-01-2026,26155.1,26340,26118.4,26328.55,182.0,.7,357547806,23770.13,22.92,3.58,1.28\n"
        b"Nifty 500,02-01-2026,23935.95,24107.7,23921.45,24099.0,189.45,.79,3709759369,76298.98,24.69,3.75,1.14\n")


def test_parse_and_validate():
    df = index_close.parse_index(BODY)
    assert list(df['symbol']) == ['Nifty 50', 'Nifty 500']
    assert df.loc[1, 'close'] == 24099.0 and str(df.loc[1, 'date'].date()) == '2026-01-02'
    assert index_close.validate(df)['missing_baseline'] == 0


def test_rejects_other_layouts():
    import pytest
    with pytest.raises(ValueError):
        index_close.parse_index(b'a,b\n1,2\n')
