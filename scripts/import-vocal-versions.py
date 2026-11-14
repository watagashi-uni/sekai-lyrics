"""Import rendition-specific historical alignments and accepted upstream line timings.
Input directory contains selected read-only artifacts, online master, and checkout.
"""
import json,sys,subprocess,tempfile,re
from difflib import SequenceMatcher
from pathlib import Path
from merge_common import rows,normalize
root=Path(__file__).resolve().parents[1];work=Path(sys.argv[1])
load=lambda p:json.loads(p.read_text())
write=lambda p,d:p.write_text(json.dumps(d,ensure_ascii=False,separators=(',',':')))
vocals=load(work/'musicVocals.json');byid={v['id']:v for v in vocals}
names={r['id']:r.get('firstName','')+r.get('givenName','') for r in load(work/'gameCharacters.json')}
outside={r['id']:r['name'] for r in load(work/'outsideCharacters.json')}

def performers(v):
 result=[]
 for c in v['characters']:
  cid=c['characterId']
  if c['characterType']=='game_character':result.append({'performerId':f'歌唱者-{cid:02}','name':names[cid],'characterId':cid})
  else:result.append({'performerId':f'外部歌唱者-{cid}','name':outside[cid],'characterId':None,'outsideCharacterId':cid})
 return result

def annotate(ps):
 for p in ps:
  match=re.fullmatch(r'歌唱者-(\d+)',str(p['performerId']));p['characterId']=int(match[1]) if match else (p['performerId'] if isinstance(p['performerId'],int) else None)
 return ps

def compact(line,base):
 for i,b in enumerate(base):
  if line['text']==b['text'] and line.get('translation')==b.get('translation'):
   line['textRef']=i;line.pop('text');line.pop('translation',None);break
 return line

def save(mid,version,source):
 folder=root/'lyrics'/f'{mid:04}';p=folder/'lyrics.json';d=load(p)
 if version['vocalId']==d.get('vocalId') or version['assetbundle']==d.get('assetbundle'):return False
 if any(v['vocalId']==version['vocalId'] for v in d.get('versions',[])):return False
 base=rows(d)
 version['lines']=[compact(line,base) for line in version['lines']]
 d.setdefault('versions',[]).append(version);d['versions'].sort(key=lambda v:v['vocalId']);write(p,d)
 sp=folder/'sources.json';s=load(sp);s['sources'].append(source);sp.write_text(json.dumps(s,ensure_ascii=False,indent=2)+'\n');return True

report={'A':[],'B':[],'skipped':[]}
statuses={j['job_id']:j for j in load(work/'snapshots/20261110-all-v2/summary.json')['jobs']}
for job in load(work/'selected.json'):
 mid=job['music_id'];jid=job['job_id'];out=work/'snapshots/20261110-all-v2/jobs'/jid/'output'
 project=load(work/'lyrics'/f'music_{mid}.json')
 rendition=next(r for r in project['renditions'] if r['key']==job['rendition_key'])
 overlay=load(out/'timing-overlay.json');duration=overlay.get('duration')
 if duration is None and (out/'cut-map.json').exists():duration=load(out/'cut-map.json')['target_duration']
 if not duration:report['skipped'].append({'job':jid,'reason':'no duration'});continue
 canonical={r['id']:r for r in rendition[job['lyrics_version']]['lines']}
 ps=annotate(rendition.get('performers',[]));known={p['performerId'] for p in ps}
 ls=[]
 for group in load(out/'bilingual-lines.json'):
  if not 0<=group['start']<group['end']<=duration+0.00001:continue
  for raw in group['lines']:
   src=canonical.get(raw['line_id'])
   if not src or src['japanese']!=raw['japanese']:continue
   line={'text':raw['japanese'],'start':group['start'],'end':min(group['end'],duration)}
   if src.get('zh-CN'):line['translation']=src['zh-CN']
   segments=[{'text':s['text'],'performerIds':s.get('performerIds',[])} for s in src.get('segments',[])]
   if segments and ''.join(s['text'] for s in segments)==line['text'] and all(p in known for s in segments for p in s['performerIds']):line['segments']=segments
   ids=src.get('trailingPerformerIds',[])
   if ids and all(i in known for i in ids):line['performerIds']=ids
   ls.append(line)
 ls.sort(key=lambda l:l['start'])
 if not ls:report['skipped'].append({'job':jid,'reason':'no valid lines'});continue
 credits=load(out/'credits.json')
 v={'vocalId':job['vocal_id'],'assetbundle':job['assetbundle'],'duration':duration,'performers':ps,'source':'A','lines':ls,'credits':credits.get('translation',{}),'alignmentStatus':statuses[jid]['status']}
 source={'usage':'附加演唱版本','provider':'historical alignment','url':None,'license':None,'vocalId':v['vocalId'],'source':'A','jobId':jid,'timingSource':credits.get('timing_source'),'performerSource':job['rendition_key'],'provenance':credits.get('provenance',[]),'note':'Snapshot 20261110-all-v2; only recorded aligned lines; no cross-version word transfer; shared intervals retained; sub-10-microsecond rounding excess clamped to decoded duration.'}
 if save(mid,v,source):report['A'].append({'musicId':mid,'vocalId':v['vocalId'],'jobId':jid,'lines':len(ls)})
 else:report['skipped'].append({'job':jid,'reason':'default or duplicate vocal'})

for audit in load(root/'reports/timing-comparison.json')['songs']:
 if audit.get('sameVocal') or 'vocalId' not in audit:continue
 mid=audit['musicId'];vid=audit['vocalId'];folder=root/'lyrics'/f'{mid:04}';d=load(folder/'lyrics.json')
 if any(v['vocalId']==vid for v in d.get('versions',[])):continue
 if audit['verdict'] not in ['ok','ok-agree']:
  report['skipped'].append({'musicId':mid,'vocalId':vid,'reason':'B verdict review'});continue
 v=byid[vid];asset=v['assetbundleName']
 with tempfile.TemporaryDirectory(dir=work) as tmp:
  audio=Path(tmp)/'audio.mp3'
  try:
   subprocess.run(['curl','-fLsS','--max-time','60',f'https://assets-direct.unipjsk.com/ondemand/music/long/{asset}/{asset}.mp3','-o',str(audio)],check=True,capture_output=True)
   duration=float(subprocess.check_output(['ffprobe','-v','error','-show_entries','format=duration','-of','default=noprint_wrappers=1:nokey=1',str(audio)]))
  except Exception as e:report['skipped'].append({'musicId':mid,'vocalId':vid,'reason':'duration unavailable '+type(e).__name__});continue
 base=rows(d);ps=performers(v);known={p['performerId'] for p in ps};ls=[]
 # Only transfer existing translations for exact text with an unambiguous value.
 translations={}
 for b in base:translations.setdefault(normalize(b['text']),set()).add(b.get('translation'))
 for raw in load(work/'upstream/timed'/f'{mid:04}.json'):
  start=round(raw['startTime']+audit['fillerSec'],6);end=round(raw['endTime']+audit['fillerSec'],6)
  if raw['startTime']<=0 or not 0<=start<end<=duration:continue
  line={'text':raw['text'],'start':start,'end':end}
  ts=translations.get(normalize(raw['text']),set())
  if len(ts)==1 and next(iter(ts)):line['translation']=next(iter(ts))
  ids=[f'歌唱者-{c:02}' for c in raw['characterIds']]
  if ids and all(i in known for i in ids):line['performerIds']=ids
  ls.append(line)
 ls.sort(key=lambda l:l['start'])
 if not ls:continue
 version={'vocalId':vid,'assetbundle':asset,'duration':duration,'performers':ps,'source':'B','lines':ls,'credits':d.get('credits',{}),'alignmentStatus':'partial_line_alignment'}
 source={'usage':'附加演唱版本','provider':'shinonomeenana/sekai_lyrics','url':'https://github.com/shinonomeenana/sekai_lyrics','license':None,'source':'B','vocalId':vid,'verdict':audit['verdict'],'fillerSec':audit['fillerSec'],'performerSource':'line characterIds; no segment inference','note':'Translations only reused from local exact text; no upstream translation imported. Zero starts excluded.'}
 if save(mid,version,source):report['B'].append({'musicId':mid,'vocalId':vid,'lines':len(ls)})
# Prefer rendition-specific segmentation for B, matching actual occurrence order.
manifest=load(work/'manifest.json')['jobs']
for p in (root/'lyrics').glob('*/lyrics.json'):
 d=load(p);changed=False
 for v in d.get('versions',[]):
  if v['source']!='B':continue
  job=next((j for j in manifest if j['vocal_id']==v['vocalId']),None)
  project_file=work/'lyrics'/f"music_{d['musicId']}.json"
  if not job or not project_file.exists():continue
  rendition=next(r for r in load(project_file)['renditions'] if r['key']==job['rendition_key'])
  canonical=rendition[job['lyrics_version']]['lines'];base=rows(d)
  texts=[base[l['textRef']]['text'] if 'textRef' in l else l['text'] for l in v['lines']]
  known={x['performerId'] for x in v['performers']};count=0
  for block in SequenceMatcher(None,texts,[r['japanese'] for r in canonical],autojunk=False).get_matching_blocks():
   for offset in range(block.size):
    line=v['lines'][block.a+offset];src=canonical[block.b+offset]
    segments=[{'text':s['text'],'performerIds':s.get('performerIds',[])} for s in src.get('segments',[])]
    if not segments or ''.join(s['text'] for s in segments)!=src['japanese'] or not all(i in known for s in segments for i in s['performerIds']):continue
    line['segments']=segments;line.pop('performerIds',None)
    if src.get('trailingPerformerIds'):line['performerIds']=src['trailingPerformerIds']
    count+=1
  if count:
   changed=True;sp=p.with_name('sources.json');provenance=load(sp)
   for item in provenance['sources']:
    if item.get('source')=='B' and item.get('vocalId')==v['vocalId']:
     item['performerSource']=f"pjsk.moe rendition {job['rendition_key']}: {count} exact ordered lines; remaining lines use upstream characterIds"
     item['performerProvenance']=rendition.get('provenance',[])
   sp.write_text(json.dumps(provenance,ensure_ascii=False,indent=2)+'\n')
 if changed:write(p,d)
# Add explicit game IDs without altering default timing/assignment.
for p in (root/'lyrics').glob('*/lyrics.json'):
 d=load(p)
 if 'performers' in d:annotate(d['performers']);write(p,d)
report['A']=[];report['B']=[]
for p in (root/'lyrics').glob('*/lyrics.json'):
 d=load(p)
 for v in d.get('versions',[]):
  if v['source'] in ['A','B']:report[v['source']].append({'musicId':d['musicId'],'vocalId':v['vocalId'],'lines':len(v['lines'])})
report['skipped']=[r for r in report['skipped'] if r['reason']!='default or duplicate vocal']
(root/'reports/version-import.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
print({k:len(v) for k,v in report.items()})
