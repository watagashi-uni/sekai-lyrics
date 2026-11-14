"""Refresh the public merge report from installed data and temporary audit results."""
import json,sys
from collections import Counter
from pathlib import Path
root=Path(__file__).resolve().parents[1];work=Path(sys.argv[1]);report_path=root/'reports/merge-report.json'
r=json.loads(report_path.read_text());counts={k:[] for k in 'ABCD'};installed={};defaults={}
for p in (root/'lyrics').glob('*/lyrics.json'):
 d=json.loads(p.read_text());defaults[d['musicId']]=d
 for v in d.get('versions',[]):
  entry={'musicId':d['musicId'],'vocalId':v['vocalId'],'lines':len(v['lines'])}
  counts[v['source']].append(entry);installed[v['vocalId']]=entry
vocals=json.loads((work/'musicVocals.json').read_text());targets=[]
for v in vocals:
 d=defaults.get(v['musicId'])
 if d and v['id']!=d.get('vocalId') and v['assetbundleName']!=d.get('assetbundle'):targets.append(v)
map_path=root/'reports/audio-version-mapping.json';mapping=json.loads(map_path.read_text()) if map_path.exists() else []
audit={a['vocalId']:a for a in mapping};skipped=[]
for v in targets:
 if v['id'] in installed:continue
 a=audit.get(v['id'])
 skipped.append({'musicId':v['musicId'],'vocalId':v['id'],'assetbundle':v['assetbundleName'],'reason':a.get('reason') if a else 'not checked','failedChecks':a.get('failedChecks',[]) if a else []})
(root/'reports/skipped-versions.json').write_text(json.dumps(skipped,ensure_ascii=False,indent=2)+'\n')
pilot=json.loads((work/'audio-pilot.json').read_text())
r['task3']={'masterDataVersion':'7.1.0.60','format':'optional versions[] with own timing, performers, credits; textRef inherits only display text/translation/ruby/romaji, never timing or singing assignments','indexVersion':1,'totalAdditionalVersions':len(installed),'songsWithAdditionalVersions':len(set(x['musicId'] for x in installed.values())),'bySource':{k:{'versions':len(v),'songs':len(set(x['musicId'] for x in v)),'lines':sum(x['lines'] for x in v)} for k,v in counts.items()},'historicalCandidates':{'jobs':90,'songs':71,'uniqueVocals':88,'note':'Two duplicate vocal IDs represented by multiple rendition keys; first manifest rendition retained. Only success/partial_alignment selected.'},'masterOtherVersions':len(targets),'masterSoloVersions':sum(len(v['characters'])==1 for v in targets),'pilot':{'songs':len(set(a['musicId'] for a in pilot)),'versions':len(pilot),'accepted':sum(a['accepted'] for a in pilot)},'audioCheckedVersions':len(mapping),'skipReasons':dict(Counter(a['reason'] for a in skipped)),'frontendChanges':['Read versions by selected musicVocal ID; unknown vocals must not reuse default timing','Resolve textRef against original default row order, copying only display fields','Apply each version duration, performers and own line timing; no words means line highlighting','Apply optional LRC lineTimings before wordLines','Use explicit characterId; outsideCharacterId identifies external singers'],'verification':['722 default versions compared to main: only documented end changes and additive romaji/metadata','node scripts/build-playback.mjs and node scripts/validate.mjs','node scripts/test-version-schema.mjs','Synthetic audio controls: known 1s offset accepted; silence, unrelated audio and unsupported middle section rejected'],'limitations':['Waveform constant-offset mappings only; inconsistent edits and weak support skipped, no spectral or vocal-isolation fallback','Additional versions are line-only; no cross-version word timing fabricated','Historical partial alignment/missing lines remain partial','Excel not regenerated; frontend untouched; no Git push or CDN upload'],'details':['version-import.json','audio-version-mapping.json','skipped-versions.json']}
report_path.write_text(json.dumps(r,ensure_ascii=False,indent=2)+'\n')
print(json.dumps(r['task3'],ensure_ascii=False,indent=2))
