"""Install accepted constant audio maps as line-only versions (no inherited split singing)."""
import json,sys
from pathlib import Path
from merge_common import rows
root=Path(__file__).resolve().parents[1];work=Path(sys.argv[1])
load=lambda p:json.loads(p.read_text())
vocals={v['id']:v for v in load(work/'musicVocals.json')}
names={r['id']:r.get('firstName','')+r.get('givenName','') for r in load(work/'gameCharacters.json')}
outside={r['id']:r['name'] for r in load(work/'outsideCharacters.json')}
results=[]
for filename in ['audio-pilot.json','audio-batch.json']:
 p=work/filename
 if p.exists():results+=load(p)
report=[];seen=set()
for result in results:
 vid=result['vocalId']
 if vid in seen:continue
 seen.add(vid)
 record={k:v for k,v in result.items() if k!='windows'}
 if not result['accepted'] and result.get('windows'):
  good=[w for w in result['windows'] if w['score']>=.65 and abs(w['offset']-result['sourceMinusTarget'])<=.02]
  failures=[]
  if result['coverage']<.9:failures.append('consistent window coverage below 90%')
  if result['medianScore']<.8:failures.append('median waveform correlation below 0.8')
  if len(good)<10:failures.append('fewer than 10 supported windows')
  if good:
   if max((b['targetStart']-a['targetStart'] for a,b in zip(good,good[1:])),default=999)>8:failures.append('unsupported gap exceeds 8 seconds')
   if good[0]['targetStart']>12:failures.append('unsupported beginning')
   if result['duration']-good[-1]['targetStart']-6>10:failures.append('unsupported ending')
  if abs(result['referenceDuration']-result['duration']-result['sourceMinusTarget'])>2:failures.append('duration/offset inconsistent')
  record['failedChecks']=failures

 if not result['accepted']:report.append(record);continue
 folder=root/'lyrics'/f"{result['musicId']:04}";p=folder/'lyrics.json';data=load(p)
 existing=next((v for v in data.get('versions',[]) if v['vocalId']==vid),None)
 if existing:
  same=existing['source']==result['source'] and existing['source'] in ['C','D']
  record.update(imported=same,reason='already installed from this verified map' if same else 'already covered by higher-priority source');report.append(record);continue
 base=rows(data);off=result['sourceMinusTarget'];duration=result['duration']
 if any(l['start']-off<0 or l['end']-off>duration or l['end']<=l['start'] for l in base):
  record.update(imported=False,reason='mapped lyrics outside audio bounds or invalid interval');report.append(record);continue
 performers=[]
 for c in vocals[vid]['characters']:
  cid=c['characterId']
  if c['characterType']=='game_character':performers.append({'performerId':f'歌唱者-{cid:02}','characterId':cid,'name':names[cid]})
  else:performers.append({'performerId':f'外部歌唱者-{cid}','characterId':None,'outsideCharacterId':cid,'name':outside[cid]})
 lines=[]
 for i,l in enumerate(base):
  line={'textRef':i,'start':round(l['start']-off,6),'end':round(l['end']-off,6)}
  if len(performers)==1:line['performerIds']=[performers[0]['performerId']]
  lines.append(line)
 lines.sort(key=lambda l:l['start'])
 version={'vocalId':vid,'assetbundle':result['assetbundle'],'duration':duration,'source':result['source'],'performers':performers,'lines':lines,'credits':data.get('credits',{}),'alignmentStatus':'audio_verified_line_mapping'}
 data.setdefault('versions',[]).append(version);data['versions'].sort(key=lambda v:v['vocalId']);p.write_text(json.dumps(data,ensure_ascii=False,separators=(',',':')))
 s=load(folder/'sources.json');s['sources'].append({'usage':'附加演唱版本','provider':'game audio waveform mapping','url':f"https://assets-direct.unipjsk.com/ondemand/music/long/{result['assetbundle']}/{result['assetbundle']}.mp3",'license':None,'vocalId':vid,'source':result['source'],'referenceVocalId':result['referenceVocalId'],'performerSource':'musicVocals 7.1.0.60; solo whole-song attribution' if len(performers)==1 else 'musicVocals 7.1.0.60 list only; no line attribution','mapping':{k:result[k] for k in ['sourceMinusTarget','coverage','medianScore','duration','referenceDuration','windows']},'note':'6-second windows every 4 seconds; >=90% consistent within 20ms, score>=0.65, median>=0.8, max supported gap 8s, bounded tails. Line-only; no inherited words or segments. Lyrics licenses/translation credits remain those of default version.'});(folder/'sources.json').write_text(json.dumps(s,ensure_ascii=False,indent=2)+'\n')
 record['imported']=True;report.append(record)
(root/'reports/audio-version-mapping.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
print('imported',sum(r.get('imported',False) for r in report),'of',len(report))
