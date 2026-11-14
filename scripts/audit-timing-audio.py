"""Measure mixture energy only; never use this as singing onset verification.
Run with numpy and a temporary work directory. Downloads are removed per song.
"""
import json,subprocess,tempfile,sys
from pathlib import Path
import numpy as np
work=Path(sys.argv[1])
root=Path(__file__).resolve().parents[1]
r=json.loads((root/'reports/timing-comparison.json').read_text());output=[]
for song in r['songs']:
 if not song.get('sameVocal') or not song.get('candidates'):continue
 if song['verdict']=='review' and song['musicId'] not in [54,731,766]:continue
 asset=song['assetbundle'];url=f'https://assets-direct.unipjsk.com/ondemand/music/long/{asset}/{asset}.mp3'
 with tempfile.TemporaryDirectory(dir=work) as tmp:
  f=Path(tmp)/'audio.mp3'
  subprocess.run(['curl','-fLsS','--max-time','60',url,'-o',str(f)],check=True)
  raw=subprocess.check_output(['ffmpeg','-v','error','-i',str(f),'-ac','1','-ar','8000','-f','f32le','-'])
  x=np.frombuffer(raw,dtype='<f4');results=[]
  for line in song['candidates']:
   values=[]
   for start in [line['before'][0],line['proposed'][0]]:
    clip=x[max(0,int(start*8000)):int((start+.25)*8000)]
    values.append(round(float(np.sqrt(np.mean(clip**2))),6) if len(clip) else None)
   results.append({'line':line['line'],'rms250msBeforeProposed':values})
  output.append({'musicId':song['musicId'],'assetbundle':asset,'duration':len(x)/8000,'evidence':results,'conclusion':'Full-mix energy cannot distinguish accompaniment from vocals; no onset correction authorized by this evidence.'})
  (root/'reports/timing-audio-check.json').write_text(json.dumps(output,ensure_ascii=False,indent=2)+'\n')
  print(song['musicId'],flush=True)
