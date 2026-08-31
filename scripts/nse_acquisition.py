"""NSE-only acquisition engine. Keeps NSE transport/parsing independent from BSE."""
from __future__ import annotations
import os,time
from datetime import date,datetime,timedelta
from io import StringIO
import pandas as pd,requests
TARGET_DATE=os.getenv('TARGET_DATE','2026-08-31'); D=date.fromisoformat(TARGET_DATE)
UA='Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/139.0 Safari/537.36'
def _result(dataset,method,**kw): return {'source':'NSE','dataset':dataset,'method':method,**kw}
def _csv(text):
 try:
  df=pd.read_csv(StringIO(text),dtype=str,keep_default_na=False); df.columns=[str(c).strip() for c in df.columns]; return df,None
 except Exception as e:return pd.DataFrame(),str(e)
def acquire():
 s=requests.Session();s.headers.update({'User-Agent':UA,'Accept':'text/csv,application/json,text/plain,*/*','Accept-Language':'en-US,en;q=0.9','Referer':'https://www.nseindia.com/companies-listing/corporate-filings-insider-trading','Connection':'keep-alive'})
 out=[]
 try:r=s.get('https://www.nseindia.com/',timeout=20);out.append(_result('homepage','direct',status_code=r.status_code))
 except Exception as e:out.append(_result('homepage','direct',status='error',error=str(e)))
 # Test filing windows independently; never infer completeness from HTTP 200.
 for label,fr,to in [('target_day',D,D),('five_days',D-timedelta(days=5),D),('thirty_days',D-timedelta(days=30),D),('one_year',D-timedelta(days=365),D)]:
  url=f'https://www.nseindia.com/api/corporates-pit?index=equities&from_date={fr:%d-%m-%Y}&to_date={to:%d-%m-%Y}&csv=true'
  try:
   t=time.perf_counter();r=s.get(url,timeout=30);elapsed=round(time.perf_counter()-t,3);rec=_result('insider_trading',f'direct_csv_{label}',status_code=r.status_code,elapsed_s=elapsed,bytes=len(r.content),content_type=r.headers.get('content-type',''))
   if r.ok and 'text/csv' in r.headers.get('content-type','').lower():
    df,err=_csv(r.text);rec.update(raw_count=len(df),columns=list(df.columns),parse_error=err)
    if len(df):
     rec['sample']=df.head(3).to_dict('records');rec['date_columns']=[c for c in df.columns if 'DATE' in c.upper() or 'BROADCAST' in c.upper()];rec['date_ranges']={c:sorted(set(df[c].astype(str).str.strip()))[:30] for c in rec['date_columns']}
   else:rec['body_prefix']=r.text[:300]
   out.append(rec)
  except Exception as e:out.append(_result('insider_trading',f'direct_csv_{label}',status='error',error=str(e)))
 try:
  from nse import NSE
  with NSE(download_folder='artifacts/nse',server=True,timeout=30) as nse:
   for kind in ('bulk_deals','block_deals'):
    try:rows=nse.bulkdeals(kind,datetime.combine(D,datetime.min.time()),datetime.combine(D,datetime.min.time()));out.append(_result(kind,'nse_package_server',status='success',count=len(rows),sample_keys=sorted(rows[0].keys()) if rows else []))
    except Exception as e:out.append(_result(kind,'nse_package_server',status='error',error=str(e)))
 except Exception as e:out.extend([_result(k,'nse_package_server',status='error',error=str(e)) for k in ('bulk_deals','block_deals')])
 return out
if __name__=='__main__':
 import json;print(json.dumps(acquire(),indent=2,default=str))
