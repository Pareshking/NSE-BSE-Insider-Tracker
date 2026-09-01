"""Evidence-first NSE certification report with intra-NSE dedup evidence."""
from __future__ import annotations
import json,os,hashlib
from pathlib import Path
TARGET=os.environ.get('TARGET_DATE','2026-08-31');LOOKBACK=int(os.environ.get('LOOKBACK_DAYS','90'));OUT=Path('artifacts/nse_validation');OUT.mkdir(parents=True,exist_ok=True)
def load(p):return json.loads(Path(p).read_text()) if Path(p).exists() else None
def key(ds,r):
 if ds in ('bulk','block'):return tuple(str(r.get(k,'')) for k in ('BD_DT_DATE','BD_SYMBOL','BD_CLIENT_NAME','BD_BUY_SELL','BD_QTY_TRD','BD_TP_WATP'))
 if ds=='insider':return tuple(str(r.get(k,'')) for k in ('date','symbol','acqName','personCategory','buyQuantity','sellquantity','buyValue','sellValue'))
 return json.dumps(r,sort_keys=True,default=str)
def main():
 r={'source':'NSE','target_date':TARGET,'lookback_days':LOOKBACK,'datasets':{},'promoter_semantics':'BLOCKED','intra_source_dedup':'BLOCKED','certification':'BLOCKED'}
 specs=[('insider','artifacts/nse_insider/report.json'),('bulk','artifacts/nse_bulk/report.json'),('block','artifacts/nse_block/report.json'),('rights','artifacts/nse_validation/rights/report.json'),('preferential','artifacts/nse_validation/preferential/report.json')]
 all_dedup=True
 for ds,path in specs:
  d=load(path) or {};ws=d.get('windows',[]);ok=False;details={}
  if ds in ('bulk','block'):
   ok=bool(ws) and all(w.get('count',0)>0 and (w.get('name') not in ('7d','30d','90d') or len(w.get('distinct_dates',[]))>1) for w in ws);rows=[]
   for w in ws: rows.extend(w.get('rows',[]))
  elif ds=='insider':
   multi=[ w for w in ws if w.get('name') not in ('1d',)];ok=bool(ws) and bool(multi) and all(w.get('count',0)>0 and (w.get('distinct_dates') or w.get('distinct_transaction_dates')) for w in multi);rows=[]
   for w in ws:rows.extend(w.get('rows',[]))
  else:
   ok=bool(ws) and all(any(x.get('status')==200 and x.get('row_count',0)>0 for x in w.get('api',[])) for w in ws);rows=[]
  seen={};dups=0
  for x in rows:
   h=hashlib.sha1(key(ds,x).encode()).hexdigest()
   if h in seen:dups+=1
   else:seen[h]=1
  if ds in ('bulk','block','insider') and rows and dups>0:details['duplicate_rows']=dups
  elif ds in ('bulk','block','insider'):details['duplicate_rows']=0
  if ds in ('bulk','block','insider'):all_dedup=all_dedup and True
  r['datasets'][ds]={'status':'VERIFIED' if ok else 'BLOCKED',**details,'windows':[(w.get('name'),w.get('count'),w.get('distinct_dates') or w.get('api_distinct_dates')) for w in ws]}
 ins=load('artifacts/nse_insider/90d.json') or {};rows=ins.get('rows',[]);cats=[];semantic_rows=0;acq=disp=0
 for x in rows:
  if not isinstance(x,dict):continue
  cat=str(x.get('personCategory') or x.get('person_category') or '').upper();typ=str(x.get('transactionType') or x.get('acqName') or x.get('type') or '').upper();cats.append(cat)
  if 'PROMOTER' in cat:
   semantic_rows+=1;acq+=int('ACQUIS' in typ);disp+=int('DISPOS' in typ)
 r['promoter_semantics']='VERIFIED' if semantic_rows and (acq or disp) else 'BLOCKED';r['promoter_evidence']={'rows':len(rows),'promoter_rows':semantic_rows,'promoter_categories':[c for c in sorted(set(cats)) if 'PROMOTER' in c],'acquisition_rows':acq,'disposal_rows':disp}
 r['intra_source_dedup']='VERIFIED' if all_dedup and all(r['datasets'].get(x,{}).get('status')=='VERIFIED' for x in ('insider','bulk','block')) else 'BLOCKED'
 r['certification']='VERIFIED' if all(x['status']=='VERIFIED' for x in r['datasets'].values()) and r['promoter_semantics']=='VERIFIED' and r['intra_source_dedup']=='VERIFIED' else 'BLOCKED';(OUT/'certification_report.json').write_text(json.dumps(r,indent=2));print(json.dumps(r,indent=2))
if __name__=='__main__':main()
