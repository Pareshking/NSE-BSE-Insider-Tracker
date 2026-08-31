"""NSE-only acquisition engine. Keeps NSE transport/parsing independent from BSE."""
from __future__ import annotations
import os,time,json
from datetime import date,datetime,timedelta
from io import StringIO
import pandas as pd,requests
TARGET_DATE=os.getenv('TARGET_DATE','2026-08-31'); D=date.fromisoformat(TARGET_DATE)
UA='Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/139.0 Safari/537.36'
def _result(dataset,method,**kw): return {'source':'NSE','dataset':dataset,'method':method,**kw}
def _parse_payload(r):
    ctype=r.headers.get('content-type','').lower()
    text=r.text
    # NSE currently supports a JSON response from this endpoint; CSV is a UI download
    # mode and has intermittently returned headers-only responses to automation.
    try:
        obj=r.json()
        if isinstance(obj,dict):
            rows=obj.get('data')
            if isinstance(rows,list):
                return pd.DataFrame(rows,dtype=str).fillna(''), 'json', None
    except Exception:
        pass
    try:
        df=pd.read_csv(StringIO(text),dtype=str,keep_default_na=False)
        df.columns=[str(c).strip() for c in df.columns]
        return df,'csv',None
    except Exception as e:return pd.DataFrame(),'unknown',str(e)
def acquire():
 s=requests.Session();s.headers.update({'User-Agent':UA,'Accept':'application/json,text/csv,*/*','Accept-Language':'en-US,en;q=0.9','Referer':'https://www.nseindia.com/companies-listing/corporate-filings-insider-trading','Connection':'keep-alive'})
 out=[]
 try:r=s.get('https://www.nseindia.com/',timeout=20);out.append(_result('homepage','direct',status_code=r.status_code,cookies=list(s.cookies.keys())))
 except Exception as e:out.append(_result('homepage','direct',status='error',error=str(e)))
 for label,fr,to in [('target_day',D,D),('five_days',D-timedelta(days=5),D),('thirty_days',D-timedelta(days=30),D),('one_year',D-timedelta(days=365),D)]:
  params={'index':'equities','from_date':f'{fr:%d-%m-%Y}','to_date':f'{to:%d-%m-%Y}'}
  try:
   t=time.perf_counter();r=s.get('https://www.nseindia.com/api/corporates-pit',params=params,timeout=30);elapsed=round(time.perf_counter()-t,3)
   rec=_result('insider_trading',f'direct_{label}',status_code=r.status_code,elapsed_s=elapsed,bytes=len(r.content),content_type=r.headers.get('content-type',''),url=r.url)
   if r.ok:
    df,mode,err=_parse_payload(r);rec.update(parse_mode=mode,raw_count=len(df),columns=list(df.columns),parse_error=err)
    if len(df):
     date_cols=[c for c in df.columns if 'DATE' in c.upper() or 'BROADCAST' in c.upper() or 'DT' in c.upper()]
     rec['date_columns']=date_cols
     rec['sample']=df.head(3).to_dict('records')
     rec['date_ranges']={c:sorted(set(df[c].astype(str).str.strip()))[:50] for c in date_cols}
   else:rec['body_prefix']=r.text[:300]
   out.append(rec)
  except Exception as e:out.append(_result('insider_trading',f'direct_{label}',status='error',error=str(e)))
 try:
  from nse import NSE
  with NSE(download_folder='artifacts/nse',server=True,timeout=30) as nse:
   for kind in ('bulk_deals','block_deals'):
    try:rows=nse.bulkdeals(kind,datetime.combine(D,datetime.min.time()),datetime.combine(D,datetime.min.time()));out.append(_result(kind,'nse_package_server',status='success',count=len(rows),sample_keys=sorted(rows[0].keys()) if rows else []))
    except Exception as e:out.append(_result(kind,'nse_package_server',status='error',error=str(e)))
 except Exception as e:out.extend([_result(k,'nse_package_server',status='error',error=str(e)) for k in ('bulk_deals','block_deals')])
 return out
if __name__=='__main__': print(json.dumps(acquire(),indent=2,default=str))
