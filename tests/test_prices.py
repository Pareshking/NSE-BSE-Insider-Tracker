import io
import zipfile

import pytest

from insiders_clean import prices

HEAD = ('TradDt,BizDt,Sgmt,Src,FinInstrmTp,FinInstrmId,ISIN,TckrSymb,SctySrs,XpryDt,FininstrmActlXpryDt,StrkPric,'
        'OptnTp,FinInstrmNm,OpnPric,HghPric,LwPric,ClsPric,LastPric,PrvsClsgPric,UndrlygPric,SttlmPric,OpnIntrst,'
        'ChngInOpnIntrst,TtlTradgVol,TtlTrfVal,TtlNbOfTxsExctd,SsnId,NewBrdLotQty,Rmks,Rsvd1,Rsvd2,Rsvd3,Rsvd4')
ROW = '2026-10-08,2026-10-08,CM,NSE,STK,1,INE000A01010,ABC,EQ,,,,,ABC LTD,10.0,12.0,9.5,11.0,11.0,10.0,,11.0,,,1000,11000.00,5,F1,1,,,,,'


def _csv(*rows):
    return ('\n'.join([HEAD, *rows]) + '\n').encode()


def test_parse_plain_and_zipped_agree():
    body = _csv(ROW)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w') as z:
        z.writestr('x.csv', body)
    a, b = prices.parse_udiff(body), prices.parse_udiff(buf.getvalue())
    assert a.equals(b)
    r = a.iloc[0]
    assert (r['isin'], r['symbol'], r['series'], r['close'], r['prev_close'], r['volume']) == ('INE000A01010', 'ABC', 'EQ', 11.0, 10.0, 1000)
    assert str(r['date'].date()) == '2026-10-08' and r['exchange'] == 'NSE'


def test_blank_numbers_become_missing_and_exchange_can_be_forced():
    df = prices.parse_udiff(_csv(ROW.replace('11.0,10.0,,11.0', '11.0,,,11.0')), exchange='bse')
    assert df['prev_close'].isna().all() and df['exchange'].iloc[0] == 'BSE'


def test_wrong_layout_is_rejected():
    with pytest.raises(ValueError):
        prices.parse_udiff(b'SYMBOL,SERIES\nABC,EQ\n')


def test_validate_flags_inconsistent_range():
    bad = ROW.replace('12.0,9.5,11.0', '9.0,9.5,11.0')
    rep = prices.validate_day(prices.parse_udiff(_csv(ROW, bad.replace('ABC,EQ', 'XYZ,EQ'))))
    assert rep['rows'] == 2 and rep['range_inconsistent'] == 1 and rep['duplicate_key'] == 0
