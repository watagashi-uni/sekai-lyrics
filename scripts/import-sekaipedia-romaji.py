"""Import only unambiguous exact normalized lines; input is a read-only upstream checkout."""
import json
import re
import subprocess
import sys
from pathlib import Path
from merge_common import normalize, rows

root = Path(__file__).resolve().parents[1]
upstream = Path(sys.argv[1])
report = json.loads((upstream/'tools/romaji_report.json').read_text())
revision = subprocess.check_output(['git','-C',str(upstream),'rev-parse','HEAD'],text=True).strip()
stats = {}
for folder in sorted((root/'lyrics').glob('[0-9]*')):
    mid = int(folder.name)
    source = upstream/'raw_lyrics'/f'{mid:04}.json'
    if not source.exists(): continue
    meta = report.get(str(mid), {})
    excluded = set(meta.get('heuristic_lines', []))
    candidates = {}
    for i, line in enumerate(json.loads(source.read_text())):
        key = normalize(line['text'])
        if i in excluded or not line.get('pronunciation'): continue
        candidates.setdefault(key, set()).add(line['pronunciation'])
    entries = []
    seen = set()
    for line in rows(json.loads((folder/'lyrics.json').read_text())):
        key = normalize(line['text'])
        if key in seen or not re.search(r'[ぁ-ヿ㐀-鿿]',key): continue
        seen.add(key)
        values = candidates.get(key, set())
        if len(values)==1:
            entries.append({'text':line['text'], 'romaji':next(iter(values))})
    if not entries: continue
    url = 'https://www.sekaipedia.org/wiki/'+meta['page']
    payload = {'provider':'Sekaipedia','url':url,'via':'https://github.com/shinonomeenana/sekai_lyrics','revision':revision,'license':'CC BY-SA 4.0','lines':entries}
    (folder/'romaji.sekaipedia.json').write_text(json.dumps(payload,ensure_ascii=False,indent=2)+'\n')
    provenance = json.loads((folder/'sources.json').read_text())
    provenance['sources'] = [s for s in provenance['sources'] if s.get('usage')!='罗马音']
    provenance['sources'].append({'usage':'罗马音','provider':'Sekaipedia','url':url,'license':'CC BY-SA 4.0','licenseUrl':'https://creativecommons.org/licenses/by-sa/4.0/','via':payload['via'],'revision':revision,'note':('APPEND/Full Version (upstream page override)' if mid == 388 else 'Game Version')+'; exact normalized text; heuristic lines excluded. Existing text oldid is not asserted as the romaji revision.'})
    (folder/'sources.json').write_text(json.dumps(provenance,ensure_ascii=False,indent=2)+'\n')
    stats[mid] = len(entries)
print(json.dumps({'songs':len(stats),'uniqueLines':sum(stats.values()),'focus':{i:stats.get(i,0) for i in [43,426,478,562,590,643,679]}}))
