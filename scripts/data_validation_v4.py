import json,re,os
from datetime import date,datetime
from difflib import SequenceMatcher
from pathlib import Path
import pandas as pd,requests
from io import StringIO
T=date.fromisoformat(os.getenv('TARGET_DATE','2026-08-31'));H=date.fromisoformat(os.getenv('SECOND_DATE','2026-08-28'))
OUT=Path('artifacts/data_validation_v4');OUT.mkdir(parents=True,exist_ok=True)
def nt(x):return re.sub(r'[^A-Z0-9 ]','',re.sub(r'\s+',' ',str(x or '').upper())).strip()
def nn(x):return re.sub(r'\s+',' ',re.sub(r'\b(PVT|PRIVATE|LTD|LIMITED|LLP|INC|CO|COMPANY|HUF)\b',' ',nt(x))).strip()
def ns(x):return re.sub(r'[^A-Z0-9]','',nt(x))
def num(x):
 s=re.sub(r'[^0-9.\-]','',str(x or ''))
 try:return float(s) if '.' in s else int(s)
 except:return None
def dt(x):
 for f in ('%d/%m/%Y','%d-%m-%Y','%d-%b-%Y','%d %b %Y','%d %b %y','%Y-%m-%d'):
  try:return datetime.strptime(str(x).strip(),f).date()
  except:pass
 return None
def nse(d):
 q=d.strftime('%d-%m-%Y');s=requests.Session();s.headers.update({'User-Agent':'Mozilla/5.0','Referer':'https://www.nseindia.com/','Accept':'application/json,text/plain,*/*'})
 try:s.get('https://www.nseindia.com/',timeout=20)
 except:pass
 out=[];u=f'https://www.nseindia.com/api/corporates-pit?index=equities&from_date={q}&to_date={q}&csv=true'
 try:
  r=s.get(u,timeout=30);t=r.content.decode('utf-8-sig','replace');df=pd.read_csv(StringIO(t)) if r.ok and t.lstrip().startswith(('SYMBOL','"SYMBOL')) else pd.DataFrame();out.append(('insider_trading',df.fillna('').to_dict('records'),{'method':'NSE PIT CSV','status':r.status_code,'columns':list(df.columns)}))
 except Exception as e:out.append(('insider_trading',[],{'method':'NSE PIT CSV','error':str(e)}))
 try:
  from nse import NSE
  with NSE(download_folder=str(OUT/'nse'),server=True,timeout=30) as n:
   for k in ('bulk_deals','block_deals'):
    try:rows=[dict(x) for x in n.bulkdeals(k,datetime.combine(d,datetime.min.time()),datetime.combine(d,datetime.min.time()))];out.append((k,rows,{'method':'nse package','columns':sorted(rows[0]) if rows else []}))
    except Exception as e:out.append((k,[],{'method':'nse package','error':str(e)}))
 except Exception as e:out.extend([(k,[],{'method':'nse package','error':str(e)}) for k in ('bulk_deals','block_deals')])
 return out
def norm_nse(ds,r):
 if ds=='insider_trading':return {'symbol':r.get('SYMBOL',''),'company':r.get('COMPANY',''),'person':r.get('NAME OF THE ACQUIRER/DISPOSER',''),'date_from':r.get('DATE OF ALLOTMENT/ACQUISITION FROM',''),'date_to':r.get('DATE OF ALLOTMENT/ACQUISITION TO',''),'side':r.get('ACQUISITION/DISPOSAL TRANSACTION TYPE',''),'quantity':r.get('NO. OF SECURITIES (ACQUIRED/DISPLOSED)',''),'value':r.get('VALUE OF SECURITY (ACQUIRED/DISPLOSED)',''),'broadcast_date':r.get('BROADCASTE DATE AND TIME',''),'raw':r}
 return {'event_date':r.get('BD_DT_DATE'),'symbol':r.get('BD_SYMBOL'),'company':r.get('BD_SCRIP_NAME'),'person':r.get('BD_CLIENT_NAME'),'side':r.get('BD_BUY_SELL'),'quantity':r.get('BD_QTY_TRD'),'price':r.get('BD_TP_WATP'),'raw':r}
def norm_bse(ds,r):
 if ds in ('bulk_deals','block_deals') and len(r)>=7:return {'event_date':r[0],'security_code':r[1],'security_name':r[2],'company':r[2],'person':r[3],'side':r[4],'quantity':r[5],'price':r[6],'raw':r}
 if ds=='insider_trading' and len(r)>=16:return {'security_code':r[0],'company':r[1],'person':r[2],'category':r[3],'quantity':r[6],'value':r[7],'side':r[8],'acquisition_date':r[10],'broadcast_date':r[15],'raw':r}
 return {'source_row':r,'raw':r}
def ident(x):return{**x,'company_norm':nn(x.get('company') or x.get('security_name')),'symbol_norm':ns(x.get('symbol') or x.get('security_name')),'person_norm':nn(x.get('person')),'side_norm':nt(x.get('side')),'qty_num':num(x.get('quantity')),'price_num':num(x.get('price'))}
def key(ds,x):
 if ds=='insider_trading':return(x.get('date_from') or x.get('acquisition_date'),x.get('date_to'),x['company_norm'],x['person_norm'],x['side_norm'],x['qty_num'],num(x.get('value')))
 if ds in ('rights_issue','preferential_issue'):return(x['company_norm'],nt(x.get('in_principle_stage')),nt(x.get('listing_stage')))
 return(str(dt(x.get('event_date')) or x.get('event_date')),x['company_norm'] or x['symbol_norm'],x['person_norm'],x['side_norm'],x['qty_num'],x['price_num'])
def dedup(ds,rows):
 seen={};u=[];du=[]
 for x in rows:
  k=key(ds,x)
  if k in seen:du.append({'duplicate_of':seen[k],'record':x,'key':k})
  else:seen[k]=len(u);u.append(x)
 return u,du
def match(n,b,ds):
 out=[]
 for i,a in enumerate(n):
  for j,z in enumerate(b):
   comp=SequenceMatcher(None,a['company_norm'],z['company_norm']).ratio() if a['company_norm'] and z['company_norm'] else 0;person=SequenceMatcher(None,a['person_norm'],z['person_norm']).ratio() if a['person_norm'] and z['person_norm'] else 0;q=a['qty_num'] is not None and a['qty_num']==z['qty_num'];p=a['price_num'] is not None and a['price_num']==z['price_num'];side=bool(a['side_norm'] and z['side_norm'] and a['side_norm'][0]==z['side_norm'][0]);sym=bool(a['symbol_norm'] and z['symbol_norm'] and a['symbol_norm']==z['symbol_norm']);score=(.35*comp+.25*person+.2*q+.1*p+.1*side) if ds=='insider_trading' else (.4*sym+.25*q+.2*p+.15*(person>.9))
   if score>=.8:out.append({'nse_index':i,'bse_index':j,'score':round(score,3),'policy':'candidate_same_disclosure' if ds=='insider_trading' else 'flag_only_exchange_specific'})
 return out
def main():
 report={'target_date':str(T),'historical_probe_date':str(H),'source_specific':[],'cross_exchange':[]};canon={}
 for d,label in ((T,'target'),(H,'historical')):
  for ds,rows,meta in nse(d):
   n=[ident(norm_nse(ds,r)) for r in rows];u,du=dedup(ds,n);report['source_specific'].append({'source':'NSE','dataset':ds,'label':label,'date':str(d),'raw_count':len(rows),'unique_count':len(u),'duplicate_count':len(du),'columns':meta.get('columns',[]),'method':meta.get('method'),'error':meta.get('error')})
   if label=='target':canon[('NSE',ds)]=u;Path(OUT/f'nse_{ds}.json').write_text(json.dumps(u,indent=2,default=str))
 raw=json.loads(Path('artifacts/data_validation_v4/bse_raw.json').read_text())['datasets']
 for ds,obj in raw.items():
  rows=[]
  for pg in obj['pages']:
   for r in pg['rows']:
    if ds in ('bulk_deals','block_deals') and len(r)>=7 and r[0] != 'Deal Date':rows.append(r)
    elif ds=='insider_trading' and len(r)>=16 and r[0] != 'Security Code':rows.append(r)
    elif ds in ('rights_issue','preferential_issue') and len(r)>=3 and r[0] != 'Company Name' and not re.fullmatch(r'\d+',r[0] or ''):rows.append(r)
  if ds in ('rights_issue','preferential_issue'):b=[ident({'company':r[0],'in_principle_stage':r[1],'listing_stage':r[2],'raw':r}) for r in rows]
  else:b=[ident(norm_bse(ds,r)) for r in rows]
  u,du=dedup(ds,b);report['source_specific'].append({'source':'BSE','dataset':ds,'label':'target','date':str(T),'raw_count':len(rows),'unique_count':len(u),'duplicate_count':len(du),'controls':obj.get('controls',[]),'historical_date_test':obj.get('historical_date_test'),'page_count':obj.get('page_count'),'method':'BSE Selenium paginated full-table capture'});canon[('BSE',ds)]=u;Path(OUT/f'bse_{ds}.json').write_text(json.dumps(u,indent=2,default=str))
 for ds in ('insider_trading','bulk_deals','block_deals'):
  n=canon.get(('NSE',ds),[]);b=canon.get(('BSE',ds),[]);report['cross_exchange'].append({'dataset':ds,'nse_unique':len(n),'bse_unique':len(b),'candidate_matches':match(n,b,ds),'rule':'insider candidates may represent the same disclosure; bulk/block matches are flags only and are never automatically collapsed because exchange execution venues are distinct'})
 Path(OUT/'validation_report.json').write_text(json.dumps(report,indent=2,default=str));print(json.dumps(report,indent=2,default=str))
if __name__=='__main__':main()
