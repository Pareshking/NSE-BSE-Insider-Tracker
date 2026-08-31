"""NSE Insider Trading acquisition: official NSE corporate-filings PIT endpoint."""
from __future__ import annotations
import os, json
from datetime import date, timedelta
from pathlib import Path
import requests

BASE='https://www.nseindia.com'; API=f'{BASE}/api/corporates-pit'
TARGET=date.fromisoformat(os.getenv('TARGET_DATE','2026-08-31'))
LOOKBACK=int(os.getenv('LOOKBACK_DAYS','90'))
OUT=Path('artifacts/nse_insider'); OUT.mkdir(parents=True,exist_ok=True)
UA='Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/139 Safari/537.36'

def fetch(s, start, end):
    p={'index':'equities','from_date':start.strftime('%d-%m-%Y'),'to_date':end.strftime('%d-%m-%Y')}
    r=s.get(API,params=p,timeout=40)
    result={'start':str(start),'end':str(end),'status':r.status_code,'url':r.url,'bytes':len(r.content),'content_type':r.headers.get('content-type','')}
    try:
        obj=r.json(); rows=obj.get('data',[]) if isinstance(obj,dict) else []
        result['mode']='json'; result['count']=len(rows); result['columns']=sorted(rows[0].keys()) if rows else []
        result['rows']=rows
    except Exception as e:
        result['mode']='non_json'; result['count']=0; result['parse_error']=str(e); result['prefix']=r.text[:500]; result['rows']=[]
    return result

def main():
    s=requests.Session(); s.headers.update({'User-Agent':UA,'Accept':'application/json,text/plain,*/*','Referer':f'{BASE}/companies-listing/corporate-filings-insider-trading','Accept-Language':'en-US,en;q=0.9'})
    home=s.get(BASE+'/',timeout=25)
    report={'target_date':str(TARGET),'lookback_days':LOOKBACK,'homepage_status':home.status_code,'windows':[]}
    windows=[('1d',TARGET),('7d',TARGET-timedelta(days=6)),('30d',TARGET-timedelta(days=29)),('90d',TARGET-timedelta(days=LOOKBACK-1))]
    for name,start in windows:
        x=fetch(s,start,TARGET)
        report['windows'].append({'name':name,**{k:v for k,v in x.items() if k!='rows'}})
        Path(OUT/f'{name}.json').write_text(json.dumps(x,indent=2,default=str),encoding='utf-8')
    Path(OUT/'report.json').write_text(json.dumps(report,indent=2),encoding='utf-8'); print(json.dumps(report,indent=2))
if __name__=='__main__': main()
