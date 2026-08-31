from __future__ import annotations
import json, os, re, time
from datetime import date, datetime
from io import StringIO
from pathlib import Path
import pandas as pd, requests

TARGET=date.fromisoformat(os.getenv('TARGET_DATE','2026-08-31'))
HIST=date.fromisoformat(os.getenv('SECOND_DATE','2026-08-28'))
OUT=Path('artifacts/data_validation_v3'); OUT.mkdir(parents=True,exist_ok=True)
UA='Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/139 Safari/537.36'

def txt(x): return re.sub(r'\s+',' ',str(x or '').strip())
def norm(x): return re.sub(r'[^A-Z0-9 ]','',txt(x).upper()).strip()
def person(x): return re.sub(r'\s+',' ',re.sub(r'\b(PVT|PRIVATE|LTD|LIMITED|LLP|INC|CO|COMPANY|HUF)\b',' ',norm(x))).strip()
def num(x):
 s=re.sub(r'[^0-9.\-]','',txt(x).replace(',',''))
 try:return float(s) if '.' in s else int(s)
 except:return None
def dt(x):
 for f in ('%d/%m/%Y','%d-%m-%Y','%d-%b-%Y','%d %b %Y','%d %b %y','%Y-%m-%d'):
  try:return datetime.strptime(txt(x),f).date()
  except:pass
 return None

def nse_session():
 s=requests.Session();s.headers.update({'User-Agent':UA,'Referer':'https://www.nseindia.com/','Accept':'application/json,text/plain,*/*'})
 try:s.get('https://www.nseindia.com/',timeout=20)
 except:pass
 return s

def nse_insider(d):
 q=d.strftime('%d-%m-%Y');s=nse_session();u=f'https://www.nseindia.com/api/corporates-pit?index=equities&from_date={q}&to_date={q}&csv=true'
 try:
  r=s.get(u,timeout=30);t=r.content.decode('utf-8-sig','replace')
  if r.ok and t.lstrip().startswith(('SYMBOL','"SYMBOL')):
   df=pd.read_csv(StringIO(t));return [dict(x) for x in df.fillna('').to_dict('records')],{'method':'NSE official PIT CSV','status':r.status_code,'columns':list(df.columns),'url':u}
  return [],{'method':'NSE official PIT CSV','status':r.status_code,'columns':[],'content_prefix':t[:160],'url':u}
 except Exception as e:return [],{'method':'NSE official PIT CSV','error':str(e),'url':u}

def nse_deals(kind,d):
 try:
  from nse import NSE
  with NSE(download_folder=str(OUT/'nse'),server=True,timeout=30) as api:
   rows=[dict(x) for x in api.bulkdeals(kind,datetime.combine(d,datetime.min.time()),datetime.combine(d,datetime.min.time()))]
  return rows,{'method':'nse package server','columns':sorted(rows[0]) if rows else []}
 except Exception as e:return [],{'method':'nse package server','error':str(e)}

def browser_tables(driver):
 try:dfs=pd.read_html(StringIO(driver.page_source))
 except:dfs=[]
 out=[]
 for df in dfs:
  df=df.dropna(how='all').dropna(axis=1,how='all')
  if df.empty:continue
  if isinstance(df.columns,pd.MultiIndex):
   cols=[]
   for c in df.columns:
    p=[txt(v) for v in c if txt(v) and txt(v).lower()!='nan'];cols.append(' | '.join(dict.fromkeys(p)))
   df.columns=cols
  else:df.columns=[txt(c) for c in df.columns]
  out.append({'columns':list(df.columns),'rows':df.fillna('').to_dict('records')})
 return out

def bse_collect():
 from selenium import webdriver
 from selenium.webdriver.chrome.options import Options
 o=Options()
 for a in ('--headless=new','--no-sandbox','--disable-dev-shm-usage','--disable-gpu',f'--user-agent={UA}'):o.add_argument(a)
 pages={'insider_trading':'https://www.bseindia.com/corporates/insider_trading_new?expandable=2','bulk_deals':'https://www.bseindia.com/markets/equity/EQReports/bulk_deals.aspx','block_deals':'https://www.bseindia.com/markets/equity/EQReports/block_deals.aspx','rights_issue':'https://www.bseindia.com/markets/publicissues/furtherissuesummary_ri','preferential_issue':'https://www.bseindia.com/markets/publicissues/furtherissuesummary_pref'}
 d=webdriver.Chrome(options=o);out={}
 try:
  for name,url in pages.items():
   out[name]={}
   for label,day in (('target',TARGET),('historical',HIST)):
    try:
     d.get(url);time.sleep(4);tabs=browser_tables(d);body=txt(d.find_element('tag name','body').text)
     out[name][label]={'date':day.isoformat(),'tables':tabs,'body_date_match':any(v in body for v in (day.strftime('%d/%m/%Y'),day.strftime('%d-%m-%Y'),day.strftime('%d %b %Y'),day.strftime('%d %b %y'))),'url':url}
    except Exception as e:out[name][label]={'date':day.isoformat(),'tables':[],'error':str(e),'url':url}
 finally:d.quit()
 return out

def pick(r,*names):
 for wanted in names:
  w=norm(wanted)
  for k,v in r.items():
   if norm(k)==w or w in norm(k):return v
 return ''

def canonical(source,ds,r):
 if source=='NSE':
  if ds=='insider_trading':return {'symbol':pick(r,'SYMBOL','NSE SYMBOL'),'company':pick(r,'COMPANY','COMPANY NAME'),'person':pick(r,'NAME OF THE ACQUIRER/DISPOSER','NAME OF PERSON'),'side':pick(r,'BUY/SELL','ACQUISITION/DISPOSAL TRANSACTION TYPE','TRANSACTION TYPE'),'quantity':pick(r,'NO. OF SECURITIES (ACQUIRED/DISPOSED)','NO. OF SECURITY (ACQUIRED / DISPOSED)','SECURITIES ACQUIRED / DISPOSED'),'value':pick(r,'VALUE OF SECURITY (ACQUIRED/DISPOSED)','VALUE OF SECURITIES'),'date_from':pick(r,'DATE OF ALLOTMENT/ACQUISITION FROM','FROM DATE'),'date_to':pick(r,'DATE OF ALLOTMENT/ACQUISITION TO','TO DATE'),'broadcast_date':pick(r,'BROADCASTE DATE AND TIME','DATE OF INTIMATION TO COMPANY')}
  return {'event_date':pick(r,'BD_DT_DATE'),'symbol':pick(r,'BD_SYMBOL'),'company':pick(r,'BD_SCRIP_NAME'),'person':pick(r,'BD_CLIENT_NAME'),'side':pick(r,'BD_BUY_SELL'),'quantity':pick(r,'BD_QTY_TRD'),'price':pick(r,'BD_TP_WATP'),'order_date':pick(r,'BD_DT_ORDER')}
 if ds in ('bulk_deals','block_deals'):return {'event_date':pick(r,'Deal Date'),'security_code':pick(r,'Security Code'),'company':pick(r,'Security Name'),'person':pick(r,'Client Name'),'side':pick(r,'Deal Type'),'quantity':pick(r,'Quantity'),'price':pick(r,'Price')}
 return {'company':pick(r,'Company Name'),'stage':pick(r,'In-Principle Stage'),'listing_stage':pick(r,'Listing Stage')}

def ident(x):
 y=dict(x);y['company_norm']=norm(x.get('company'));y['symbol_norm']=norm(x.get('symbol') or x.get('security_code'));y['person_norm']=person(x.get('person'));y['side_norm']=norm(x.get('side'));y['qty_num']=num(x.get('quantity'));y['price_num']=num(x.get('price'));return y

def dedup_key(ds,x):
 if ds=='insider_trading':return(x['company_norm'],x['person_norm'],x['side_norm'],x['qty_num'],dt(x.get('date_from')),dt(x.get('date_to')))
 if ds in ('bulk_deals','block_deals'):return(x['symbol_norm'] or x['company_norm'],x['person_norm'],x['side_norm'],x['qty_num'],x['price_num'],dt(x.get('event_date')))
 return None

def dedup(ds,rows):
 seen=set();u=[];du=[]
 for x in rows:
  k=dedup_key(ds,x)
  if k is None or not any(k):u.append(x);continue
  if k in seen:du.append(x)
  else:seen.add(k);u.append(x)
 return u,du

def flatten(item):
 rows=[]
 for t in item.get('tables',[]):
  rows += [dict((txt(k),txt(v)) for k,v in r.items()) for r in t.get('rows',[])]
 return rows

def summary(source,ds,rows):
 c=[ident(canonical(source,ds,r)) for r in rows];u,du=dedup(ds,c);cols=sorted(set().union(*(r.keys() for r in rows))) if rows else []
 dates=[]
 for r in u:
  for k,v in r.items():
   if 'date' in k.lower():
    d=dt(v)
    if d:dates.append(d.isoformat())
 return {'source':source,'dataset':ds,'raw_count':len(rows),'unique_count':len(u),'duplicate_count':len(du),'columns':cols,'canonical_fields':sorted(set().union(*(r.keys() for r in c))) if c else [],'date_min':min(dates) if dates else None,'date_max':max(dates) if dates else None,'sample':u[:5],'duplicates_sample':du[:10],'rows':u}

def insider_matches(n,b):
 out=[]
 for i,a in enumerate(n):
  for j,z in enumerate(b):
   comp=a['company_norm'] and z['company_norm'] and a['company_norm']==z['company_norm'];personx=a['person_norm'] and z['person_norm'] and (a['person_norm']==z['person_norm'] or a['person_norm'] in z['person_norm'] or z['person_norm'] in a['person_norm']);qty=a['qty_num'] is not None and a['qty_num']==z['qty_num'];ad=dt(a.get('date_from'));bd=dt(z.get('date_from') or z.get('broadcast_date'));same_date=ad and bd and abs((ad-bd).days)<=3
   score=int(comp)+int(personx)+int(qty)+int(same_date)
   if score>=3:out.append({'nse_index':i,'bse_index':j,'score':score,'policy':'candidate_same_disclosure'})
 return out

def main():
 report={'target_date':str(TARGET),'historical_probe_date':str(HIST),'source_specific':[],'cross_exchange':[],'errors':[]};canon={}
 for day,label in ((TARGET,'target'),(HIST,'historical')):
  for ds in ('insider_trading','bulk_deals','block_deals'):
   rows,meta=(nse_insider(day) if ds=='insider_trading' else nse_deals(ds,day));s=summary('NSE',ds,rows);s.update({'label':label,'probe_date':str(day),'method':meta.get('method'),'status':meta.get('status'),'error':meta.get('error')});s.pop('rows',None);report['source_specific'].append(s)
   if label=='target':canon[('NSE',ds)]=[ident(canonical('NSE',ds,r)) for r in rows];Path(OUT/f'nse_{ds}.json').write_text(json.dumps(canon[('NSE',ds)],indent=2,default=str))
 bse=bse_collect();Path(OUT/'bse_browser_capture.json').write_text(json.dumps(bse,indent=2,default=str))
 for ds,obj in bse.items():
  for label in ('target','historical'):
   rows=flatten(obj.get(label,{}));s=summary('BSE',ds,rows);s.update({'label':label,'probe_date':obj.get(label,{}).get('date'),'method':'BSE Selenium + pandas.read_html','body_date_match':obj.get(label,{}).get('body_date_match'),'error':obj.get(label,{}).get('error')});s.pop('rows',None);report['source_specific'].append(s)
   if label=='target':canon[('BSE',ds)]=[ident(canonical('BSE',ds,r)) for r in rows];Path(OUT/f'bse_{ds}.json').write_text(json.dumps(canon[('BSE',ds)],indent=2,default=str))
 for ds in ('insider_trading','bulk_deals','block_deals'):
  n=canon.get(('NSE',ds),[]);b=canon.get(('BSE',ds),[]);report['cross_exchange'].append({'dataset':ds,'nse_unique':len(dedup(ds,n)[0]),'bse_unique':len(dedup(ds,b)[0]),'candidate_matches':insider_matches(dedup(ds,n)[0],dedup(ds,b)[0]) if ds=='insider_trading' else [],'policy':'Insider candidates can be one disclosure published by both exchanges; Bulk/Block are exchange-specific and are never auto-collapsed.'})
 Path(OUT/'validation_report.json').write_text(json.dumps(report,indent=2,default=str));print(json.dumps(report,indent=2,default=str))
if __name__=='__main__':main()
