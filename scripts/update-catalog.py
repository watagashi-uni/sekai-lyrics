"""Refresh additive coverage metadata without changing existing catalog fields."""
import json
from pathlib import Path
p=Path(__file__).resolve().parents[1]
c=json.loads((p/'catalog.json').read_text())
totals={'sekaipediaRomajiLines':0,'generatedRomajiLines':0,'additionalVersions':0,'versionedSongs':0,'versionSources':{k:0 for k in 'ABCD'}}
for song in c['songs']:
 d=json.loads((p/song['directory']/'lyrics.json').read_text())
 lines=d.get('lines',[]) if d['format']=='bilingual_json' else d.get('romajiLines',[])
 for origin,key in [('sekaipedia','sekaipediaRomajiLines'),('generated','generatedRomajiLines')]:
  song[key]=sum(r.get('romajiSource',r.get('source'))==origin for r in lines)
  totals[key]+=song[key]
 reviewed=sum(r.get('romajiSource',r.get('source'))=='reviewed' for r in lines)
 if reviewed: song['reviewedRomajiLines']=reviewed
 else: song.pop('reviewedRomajiLines',None)
 totals['reviewedRomajiLines']=totals.get('reviewedRomajiLines',0)+reviewed
 if 'versions' in d:
  song['versions']=[{'vocalId':v['vocalId'],'assetbundle':v['assetbundle'],'duration':v['duration'],'source':v['source'],'lines':len(v['lines'])} for v in d['versions']]
  totals['additionalVersions']+=len(d['versions'])
  totals['versionedSongs']+=bool(d['versions'])
  for version in d['versions']:totals['versionSources'][version['source']]+=1
totals['totalPlaybackVersions']=len(c['songs'])+totals['additionalVersions']
c['mergeStatistics']=totals
(p/'catalog.json').write_text(json.dumps(c,ensure_ascii=False,indent=2)+'\n')
print(totals)
