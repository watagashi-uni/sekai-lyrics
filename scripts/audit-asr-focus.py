"""Summarize independent ASR exact phrase matches; never edit lyric timing.
The input is a temporary ASR transcript, not an authoritative lyric source.
"""
import json,sys
from pathlib import Path
from merge_common import normalize
root=Path(__file__).resolve().parents[1];transcripts=json.loads(Path(sys.argv[1]).read_text());comparison=json.loads((root/'reports/timing-comparison.json').read_text());output=[]
for transcript in transcripts:
 mid=transcript['musicId'];audit=next(s for s in comparison['songs'] if s['musicId']==mid)
 words=[w for s in transcript['segments'] for w in s['words'] if normalize(w['text'])]
 stream='';starts={};ends={}
 for i,w in enumerate(words):
  starts[len(stream)]=i;stream+=normalize(w['text']);ends[len(stream)]=i
 evidence=[]
 for candidate in audit['candidates']:
  key=normalize(candidate['text']);pos=stream.find(key)
  if len(key)<8 or pos<0 or stream.find(key,pos+1)>=0 or pos not in starts or pos+len(key) not in ends:continue
  selected=words[starts[pos]:ends[pos+len(key)]+1]
  confidence=sum(w['probability'] for w in selected)/len(selected)
  if confidence<.6:continue
  start=selected[0]['start']
  if min(abs(start-candidate['before'][0]),abs(start-candidate['proposed'][0]))>5:continue
  evidence.append({'line':candidate['line'],'text':candidate['text'],'defaultStart':candidate['before'][0],'upstreamStart':candidate['proposed'][0],'asrStart':round(start,3),'meanWordProbability':round(confidence,4),'note':'Exact unique phrase at observed word boundaries; ASR timing is supporting evidence only, not listening verification.'})
 output.append({'musicId':mid,'model':transcript['model'],'matchedOutlierPhrases':evidence,'conclusion':'review verdict retained; no automatic timing replacement. ASR contains lyric recognition errors and does not independently certify vocal boundaries.'})
(root/'reports/focused-asr-audit.json').write_text(json.dumps(output,ensure_ascii=False,indent=2)+'\n')
print([(r['musicId'],len(r['matchedOutlierPhrases'])) for r in output])
