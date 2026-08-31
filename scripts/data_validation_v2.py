import json, os, re, time
from datetime import date, datetime
from difflib import SequenceMatcher
from pathlib import Path
import pandas as pd
import requests
from io import StringIO

TARGET=date.fromisoformat(os.getenv('TARGET_DATE','2026-08-31'))
HIST=date.fromisoformat(os.getenv('SECOND_DATE','2026-08-28'))
OUT=Path('artifacts/data_validation_v2'); OUT.mkdir(parents=True,exist_ok=True)
UA='Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/139 Safari/537.36'

def nt(x): return re.sub(r'[^A-Z0-9 ]','',re.sub(r'\s+',' ',str(x or '').upper())).strip()
def nn(x): return re.sub(r'\s+',' ',re.sub(r'\b(PVT|PRIVATE|LTD|LIMITED|LLP|INC|CO|COMPANY|HUF)\b',' ',nt(x))).strip()
def ns(x): return re.sub(r'[^A-Z0-9]','',nt(x))
def num(x):
 s=re.sub(r'[^0-9.\-]','',str(x or ''))
 try:return float(s) if '.' in s else int(s)
 except:return None
def dt(x):
 for f in ('%d/%m/%Y','%d-%m-%Y','%d-%b-%Y','%d %b %Y','%d %b %y','%Y-%m-%d'):
  try:return datetime.strptime(str(x).strip(),f).date()
  except:pass
 return None

def session():
 s=requests.Session(); s.headers.update({'User-Agent':UA,'Accept':'application/json,text/plain,*/*','Accept-Language':'en-US,en;q=0.9','Referer':'https://www.nseindia.com/'})
 try:s.get('https://www.nseindia.com/',timeout=20)
 except:pass
 return s

def nse_insider(d):
 s=session(); q=d.strftime('%d-%m-%Y'); u=f'https://www.nseindia.com/api/corporates-pit?index=equities&from_date={q}&to_date={q}&csv=true'
 try:
  r=s.get(u,timeout=30); t=r.content.decode('utf-8-sig','replace'); df=pd.read_csv(StringIO(t)) if r.ok and t.lstrip().startswith(('SYMBOL','"SYMBOL')) else pd.DataFrame()
  return [dict(x) for x in df.fillna('').to_dict('records')],{'method':'NSE official PIT CSV','status':r.status_code,'columns':list(df.columns),'content_prefix':t[:120]}
 except Exception as e:return [],{'method':'NSE official PIT CSV','status':'error','error':str(e)}

def nse_deals(kind,d):
 try:
  from nse import NSE
  with NSE(download_folder=str(OUT/'nse'),server=True,timeout=30) as n:
   rows=[dict(x) for x in n.bulkdeals(kind,datetime.combine(d,datetime.min.time()),datetime.combine(d,datetime.min.time()))]
  return rows,{'method':'nse package server','columns':sorted(rows[0]) if rows else []}
 except Exception as e:return [],{'method':'nse package server','error':str(e)}

def browser_tables(url, symbol=None):
 from selenium import webdriver
 from selenium.webdriver.chrome.options import Options
 o=Options(); [o.add_argument(x) for x in ('--headless=new','--no-sandbox','--disable-dev-shm-usage','--disable-gpu',f'--user-agent={UA}')]
 d=webdriver.Chrome(options=o); d.get(url + ((('&' if '?' in url else '?')+f'symbol={symbol}&tabIndex=equity') if symbol else '')); time.sleep(4)
 tabs=d.execute_script("""return Array.from(document.querySelectorAll('table')).map(t=>{let rs=Array.from(t.querySelectorAll('tr')).map(r=>Array.from(r.cells).map(c=>(c.innerText||'').trim())).filter(x=>x.length);return {rows:rs,links:Array.from(t.querySelectorAll('a')).map(a=>({text:(a.innerText||'').trim(),href:a.href,onclick:a.getAttribute('onclick')||''}))}}).filter(x=>x.rows.length);""")
 inputs=d.execute_script("""return Array.from(document.querySelectorAll('input,select,button')).map(x=>({type:x.type||'',name:x.name||'',id:x.id||'',value:x.value||'',text:(x.innerText||'').trim()})).filter(x=>x.type==='date'||/date|from|to|search|go/i.test((x.name||'')+' '+(x.id||'')+' '+(x.text||'')));""")
 body=d.find_element('tag name','body').text; d.quit(); return tabs,inputs,body

def bse(d):
 pages={'bulk_deals':'https://www.bseindia.com/markets/equity/EQReports/bulk_deals.aspx','block_deals':'https://www.bseindia.com/markets/equity/EQReports/block_deals.aspx','insider_trading':'https://www.bseindia.com/corporates/insider_trading_new?expandable=2','rights_issue':'https://www.bseindia.com/markets/publicissues/furtherissuesummary_ri','preferential_issue':'https://www.bseindia.com/markets/publicissues/furtherissuesummary_pref'}
 out=[]
 from selenium import webdriver
 from selenium.webdriver.chrome.options import Options
 o=Options(); [o.add_argument(x) for x in ('--headless=new','--no-sandbox','--disable-dev-shm-usage','--disable-gpu',f'--user-agent={UA}')]
 dr=webdriver.Chrome(options=o)
 for ds,u in pages.items():
  try:
   dr.get(u); time.sleep(4)
   tabs=dr.execute_script("""return Array.from(document.querySelectorAll('table')).map(t=>({rows:Array.from(t.querySelectorAll('tr')).map(r=>Array.from(r.cells).map(c=>(c.innerText||'').trim())).filter(x=>x.length),links:Array.from(t.querySelectorAll('a')).map(a=>({text:(a.innerText||'').trim(),href:a.href,onclick:a.getAttribute('onclick')||''}))})).filter(x=>x.rows.length);""")
   controls=dr.execute_script("""return Array.from(document.querySelectorAll('input,select,button')).map(x=>({type:x.type||'',name:x.name||'',id:x.id||'',value:x.value||'',text:(x.innerText||'').trim()})).filter(x=>x.type==='date'||/date|from|to|search|go|view/i.test((x.name||'')+' '+(x.id||'')+' '+(x.text||'')));""")
   rows=[]; links=[]
   for t in tabs: rows+=t['rows']; links+=t['links']
   out.append((ds,rows,{'method':'BSE Selenium','controls':controls,'links':links,'table_count':len(tabs),'rows':len(rows),'target_date_text':any(x in dr.find_element('tag name','body').text for x in (d.strftime('%d/%m/%Y'),d.strftime('%d %b %Y'),d.strftime('%d %b %y')))}))
  except Exception as e: out.append((ds,[],{'method':'BSE Selenium','error':str(e)}))
 dr.quit(); return out

def nse_issue(ds,url,symbol):
 try:
  tabs,controls,body=browser_tables(url,symbol); rows=[]
  for t in tabs: rows+=t['rows']
  return rows,{'method':'NSE Selenium XBRL','controls':controls,'table_count':len(tabs),'symbol_probe':symbol}
 except Exception as e:return [],{'method':'NSE Selenium XBRL','error':str(e)}

def bse_rows(ds,rows):
 out=[]
 for r in rows:
  if ds in ('bulk_deals','block_deals') and len(r)>=7: x={'event_date':r[0],'security_code':r[1],'security_name':r[2],'person':r[3],'side':r[4],'quantity':r[5],'price':r[6]}
  elif ds=='insider_trading' and len(r)>=16: x={'security_code':r[0],'company':r[1],'person':r[2],'category':r[3],'holding_prior':r[4],'security_type':r[5],'quantity':r[6],'value':r[7],'transaction_type':r[8],'holding_post':r[9],'acquisition_date':r[10],'mode':r[11],'derivative_type':r[12],'derivative_spec':r[13],'notional_buy':r[14],'broadcast_date':r[15]}
  else: x={'source_row':r}
  out.append(x)
 return out

def nse_norm(ds,rows):
 out=[]
 for r in rows:
  if ds=='insider_trading': x={'symbol':r.get('SYMBOL',''),'company':r.get('COMPANY',''),'person':r.get('NAME OF THE ACQUIRER/DISPOSER',''),'category':r.get('CATEGORY OF PERSON',''),'security_type_prior':r.get('TYPE OF SECURITY (PRIOR)',''),'quantity_prior':r.get('NO. OF SECURITY (PRIOR)',''),'security_type_acquired':r.get('TYPE OF SECURITY (ACQUIRED/DISPLOSED)',''),'quantity_acquired':r.get('NO. OF SECURITIES (ACQUIRED/DISPLOSED)',''),'value':r.get('VALUE OF SECURITY (ACQUIRED/DISPLOSED)',''),'transaction_type':r.get('ACQUISITION/DISPOSAL TRANSACTION TYPE',''),'date_from':r.get('DATE OF ALLOTMENT/ACQUISITION FROM',''),'date_to':r.get('DATE OF ALLOTMENT/ACQUISITION TO',''),'initimation_date':r.get('DATE OF INITMATION TO COMPANY',''),'mode':r.get('MODE OF ACQUISITION',''),'exchange':r.get('EXCHANGE',''),'broadcast_date':r.get('BROADCASTE DATE AND TIME',''),'raw':r}
  elif ds in ('bulk_deals','block_deals'): x={'event_date':r.get('BD_DT_DATE'),'symbol':r.get('BD_SYMBOL'),'company':r.get('BD_SCRIP_NAME'),'person':r.get('BD_CLIENT_NAME'),'side':r.get('BD_BUY_SELL'),'quantity':r.get('BD_QTY_TRD'),'price':r.get('BD_TP_WATP'),'order_date':r.get('BD_DT_ORDER'),'raw':r}
  else:x={'source_row':r,'raw':r}
  out.append(x)
 return out

def identity(x): return {**x,'company_norm':nn(x.get('company') or x.get('security_name')),'symbol_norm':ns(x.get('symbol') or x.get('security_name')),'person_norm':nn(x.get('person')),'side_norm':nt(x.get('side') or x.get('transaction_type')),'quantity_num':num(x.get('quantity') or x.get('quantity_acquired')),'price_num':num(x.get('price'))}

def key(ds,x):
 if ds=='insider_trading': return (x.get('date_from'),x.get('date_to'),x['company_norm'],x['person_norm'],x['side_norm'],x['quantity_num'],num(x.get('value')))
 return (str(dt(x.get('event_date') or '') or x.get('event_date')),x['company_norm'] or x['symbol_norm'],x['person_norm'],x['side_norm'],x['quantity_num'],x['price_num'])

def dedup(ds,rows):
 seen={};u=[];dup=[]
 for x in rows:
  k=key(ds,x)
  if k in seen:dup.append({'duplicate_of':seen[k],'key':k,'record':x})
  else:seen[k]=len(u);u.append(x)
 return u,dup

def match(n,b,ds):
 out=[]
 for i,a in enumerate(n):
  for j,z in enumerate(b):
   if ds=='insider_trading':
    company=SequenceMatcher(None,a['company_norm'],z['company_norm']).ratio() if a['company_norm'] and z['company_norm'] else 0
    person=SequenceMatcher(None,a['person_norm'],z['person_norm']).ratio() if a['person_norm'] and z['person_norm'] else 0
    q=a['quantity_num'] is not None and a['quantity_num']==z['quantity_num']; side=bool(a['side_norm'] and z['side_norm'] and a['side_norm'][0]==z['side_norm'][0]); score=.4*company+.3*person+.2*q+.1*side
   else:
    sec=(a['symbol_norm']==z['symbol_norm']) if a['symbol_norm'] and z['symbol_norm'] else SequenceMatcher(None,a['company_norm'],z['company_norm']).ratio()>.92
    q=a['quantity_num'] is not None and a['quantity_num']==z['quantity_num']; p=a['price_num'] is not None and a['price_num']==z['price_num']; person=SequenceMatcher(None,a['person_norm'],z['person_norm']).ratio() if a['person_norm'] and z['person_norm'] else 0; score=.4*sec+.3*q+.2*p+.1*(person>.9)
   if score>=.8:out.append({'nse_index':i,'bse_index':j,'score':round(float(score),3),'policy':'candidate_same_disclosure' if ds=='insider_trading' else 'flag_only_exchange_specific'})
 return out

def main():
 raw=[]
 for d,label in ((TARGET,'target'),(HIST,'historical')):
  for ds,fn in [('insider_trading',nse_insider),('bulk_deals',lambda x:nse_deals('bulk_deals',x)),('block_deals',lambda x:nse_deals('block_deals',x))]:
   rows,meta=fn(d); raw.append({'source':'NSE','dataset':ds,'label':label,'date':d.isoformat(),'rows':rows,'meta':meta})
 for ds,url,sym in [('rights_issue','https://www.nseindia.com/companies-listing/corporate-filings-RI','ARL'),('preferential_issue','https://www.nseindia.com/companies-listing/corporate-filings-PREF','REPL')]:
  rows,meta=nse_issue(ds,url,sym); raw.append({'source':'NSE','dataset':ds,'label':'schema_probe','date':TARGET.isoformat(),'rows':rows,'meta':meta})
 for ds,rows,meta in bse(TARGET): raw.append({'source':'BSE','dataset':ds,'label':'target','date':TARGET.isoformat(),'rows':bse_rows(ds,rows),'meta':meta})
 report={'target_date':TARGET.isoformat(),'historical_probe_date':HIST.isoformat(),'source_specific':[],'cross_exchange':[]}; canon={}
 for it in raw:
  rows=[identity(x) for x in it['rows']]; u,du=dedup(it['dataset'],rows) if rows else ([],[])
  report['source_specific'].append({'source':it['source'],'dataset':it['dataset'],'label':it['label'],'probe_date':it['date'],'raw_count':len(it['rows']),'unique_count':len(u),'duplicate_count':len(du),'meta':it['meta'],'sample':u[:5],'duplicates':du[:20]}); canon[(it['source'],it['dataset'],it['label'])]=u
  if it['label']=='target':(OUT/f"{it['source'].lower()}_{it['dataset']}.json").write_text(json.dumps(u,indent=2,default=str))
 for ds in ('insider_trading','bulk_deals','block_deals'):
  n=canon.get(('NSE',ds,'target'),[]); b=canon.get(('BSE',ds,'target'),[])
  if n or b: report['cross_exchange'].append({'dataset':ds,'nse_unique':len(n),'bse_unique':len(b),'matches':match(n,b,ds)[:500],'rule':'insider matches are duplicate-disclosure candidates; bulk/block are never auto-collapsed because exchange execution venues are distinct'})
 (OUT/'validation_report.json').write_text(json.dumps(report,indent=2,default=str)); print(json.dumps(report,indent=2,default=str))
if __name__=='__main__': main()
