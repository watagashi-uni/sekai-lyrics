"""Audit ordered exact line matches and import conservative line endings only."""
import json
import sys
from pathlib import Path
from difflib import SequenceMatcher
from merge_common import normalize, rows
root=Path(__file__).resolve().parents[1]
work=Path(sys.argv[1]); upstream=work/'upstream'
vocals=json.loads((work/'musicVocals.json').read_text())
report=[]; different=[]; no_words=[]; partial=[]
for audit in json.loads((upstream/'tools/timing_report.json').read_text()):
 mid=audit['id']; folder=root/'lyrics'/f'{mid:04}'; f=folder/'lyrics.json'
 if not f.exists():continue
 d=json.loads(f.read_text()); local=rows(d); remote=json.loads((upstream/'timed'/f'{mid:04}.json').read_text())
 n=sum(bool(l.get('words')) for l in local)
 if not n:no_words.append(mid)
 elif n<len(local):partial.append(mid)
 choices=[v for v in vocals if v['musicId']==mid]
 wanted=set(c for r in remote for c in r['characterIds'])
 if audit.get('vocal'):
  choices=[v for v in choices if v['assetbundleName']==audit['vocal']]
 else:
  sekai=[v for v in choices if v['musicVocalType']=='sekai']
  choices=[v for v in sekai if wanted <= {c['characterId'] for c in v['characters'] if c['characterType']=='game_character'}] if sekai else choices
 choices.sort(key=lambda v:(len(v['characters']),v['seq'],v['id']))
 if not choices:
  report.append({'musicId':mid,'skip':'cannot resolve vocal'});continue
 v=choices[0];same=v['id']==d.get('vocalId') or v['assetbundleName']==d.get('assetbundle')
 if not same:different.append(mid)
 out={'musicId':mid,'vocalId':v['id'],'assetbundle':v['assetbundleName'],'sameVocal':same,'verdict':audit['verdict'],'fillerSec':audit['fillerSec'],'changes':[],'candidates':[]}
 matcher=SequenceMatcher(None,[normalize(l['text']) for l in local],[normalize(l['text']) for l in remote],autojunk=False)
 for block in matcher.get_matching_blocks():
  for offset in range(block.size):
   i,j=block.a+offset,block.b+offset; a,b=local[i],remote[j]
   start=round(b['startTime']+audit['fillerSec'],6);end=round(b['endTime']+audit['fillerSec'],6)
   delta=round(start-a['start'],6)
   if a.get('words'):continue
   detail={'line':i,'upstreamLine':j,'text':a['text'],'before':[a['start'],a['end']],'proposed':[start,end]}
   if abs(delta)>.3:out['candidates'].append(detail)
   # Zero starts are conservatively excluded even if the report count is absent.
   if not same or audit['verdict'] not in ['ok','ok-agree'] or b['startTime']<=0:continue
   # Only endings of closely agreeing, unambiguously matched lines. No onset changes.
   if abs(delta)>.3 or not a['start']<end<=d['duration'] or end>a['end'] or abs(end-a['end'])<.01:continue
   if d['format']=='lrc':
    entry={'cueStart':a['cueStart'],'text':a['text'],'start':a['start'],'end':end,'source':'sekai_lyrics'}
    d.setdefault('lineTimings',[]).append(entry)
   else:d['lines'][i]['end']=end
   detail['after']=[a['start'],end];out['changes'].append(detail)
 if out['changes']:
  f.write_text(json.dumps(d,ensure_ascii=False,separators=(',',':')))
  sp=folder/'sources.json';s=json.loads(sp.read_text());s['sources'].append({'usage':'逐句结束时间','provider':'shinonomeenana/sekai_lyrics','url':'https://github.com/shinonomeenana/sekai_lyrics','license':None,'vocalId':v['id'],'verdict':audit['verdict'],'fillerSec':audit['fillerSec'],'method':'ordered exact normalized text; starts agree within 0.3s; non-clamped; end shortened within existing interval; upstream vocal-silence alignment, no independent acoustic verification','lines':out['changes']});sp.write_text(json.dumps(s,ensure_ascii=False,indent=2)+'\n')
 report.append(out)
result={'noWordTiming':no_words,'partialWordTiming':partial,'differentVocal':different,'songs':report}
(root/'reports/timing-comparison.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
print({'compared':len(report),'noWords':len(no_words),'partial':len(partial),'different':len(different),'changedSongs':sum(bool(r.get('changes')) for r in report),'changedLines':sum(len(r.get('changes',[])) for r in report),'onsetCandidates':sum(len(r.get('candidates',[])) for r in report if r.get('sameVocal') and r['verdict']!='review')})
