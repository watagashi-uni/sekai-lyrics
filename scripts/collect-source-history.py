"""Run read-only on yokohama to export compact search/provenance metadata.
No lyric text, audio, credentials, or provider network requests are exported.
See build-source-history-audit.py for invocation.
"""
import json,os,re
from pathlib import Path
root=Path('/data/watagashi/lyrics-alignment-trial');out={'stage':{},'qq':{},'neteaseFiles':{},'unlabelledSearchLogs':{},'nativeSnapshot':{}}
def read(p):
 try:return json.loads(p.read_text())
 except:return None
stage=root/'round3/stage/song-lyrics-v3/songs'
for folder in stage.iterdir():
 if not folder.name.isdigit():continue
 mid=str(int(folder.name));snap=folder/'source-snapshot';job=read(snap/'job-result.json') or {};ev=read(snap/'provider-evidence.json') or {};res=read(folder/'song-result.json') or {};credits=read(snap/'credits.json') or {}
 proofs=[]
 for rec in ev.get('records',[]):
  p=rec.get('proof',{});proofs.append({k:p.get(k) for k in ['provider','record_id','source_url','source_format','provider_title','validation','source_record_file','record_sha256']})
 out['stage'][mid]={'path':str(folder),'wordAxis':res.get('word_axis'),'coverage':res.get('coverage'),'selectedJobId':job.get('job_id'),'selectedId':job.get('selected_id'),'method':job.get('method'),'timingSource':credits.get('timing_source'),'lastSourcesChecked':ev.get('last_sources_checked',[]),'wordProofs':proofs}
native=root/'deliverables/qq-native-sources';cat=read(native/'catalog.json');out['nativeSnapshot']={k:cat[k] for k in ['created_at','statistics']};records={str(r['id']):r for r in cat['records']}
for p in (native/'raw/searches').glob('*.json'):
 d=read(p)
 if not d:continue
 mid=str(d.get('music_id'));fetched=[]
 for f in d.get('fetched',[]):
  n=records.get(str(f.get('id')),{});fetched.append({**f,**{k:n.get(k) for k in ['title','artists','source_url','native_unit_count','source_format','words_json_path','has_lyric_content','content_kind']}})
 out['qq'][mid]={'path':str(p),'queries':d.get('queries',[]),'candidateCount':len(d.get('candidates',[])),'candidates':[{k:c.get(k) for k in ['id','title','artists','source_url']} for c in d.get('candidates',[])],'fetched':fetched,'errors':d.get('errors',[])}
prune={'.git','.venv','node_modules','demucs-deps','site-packages','cache','dist','blobs','models','__pycache__'}
for base,ds,fs in os.walk(root):
 ds[:]=[d for d in ds if d not in prune]
 # Paths with a song folder or job name are explicit evidence of song association.
 m=re.search(r'/(\d{4})(?:/|-\d+-)',base)
 if not m:continue
 mid=str(int(m[1]))
 if base.endswith('/sources/netease') or '/sources/netease/' in base:
  for name in fs:
   if name.endswith('.json'):
    p=Path(base)/name;d=read(p) if p.stat().st_size<3000000 else None
    out['neteaseFiles'].setdefault(mid,[]).append({'path':str(p),'recordId':p.stem,'keys':list(d) if isinstance(d,dict) else [],'format':d.get('format') if isinstance(d,dict) else None,'hasYrcKey':isinstance(d,dict) and 'yrc' in d})
 for name in fs:
  if re.match(r'candidates(?:-\d+)?\.json$',name):
   p=Path(base)/name;d=read(p)
   if isinstance(d,dict):out['unlabelledSearchLogs'].setdefault(mid,[]).append({'path':str(p),'queries':d.get('query_attempts',d.get('query')),'candidateCount':len(d.get('candidates',[]))})
print(json.dumps(out,ensure_ascii=False,separators=(',',':')))
