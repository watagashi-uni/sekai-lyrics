"""Conservative whole-recording offset verification; no word timing transfer.

uv run --no-project --with numpy --with scipy python scripts/map-vocal-audio.py WORK [pilot|batch]
Uses 6-second waveform windows every 4 seconds, searches the entire reference.
The pilot must be inspected before batch. Audio is temporary and removed per song.
"""
import json,subprocess,sys,tempfile,time,threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import numpy as np
from scipy.signal import fftconvolve

def fetch(v,folder):
 asset=v['assetbundleName'];p=folder/(asset+'.mp3')
 subprocess.run(['curl','-fLsS','--retry','1','--max-time','45',f'https://assets-direct.unipjsk.com/ondemand/music/long/{asset}/{asset}.mp3','-o',str(p)],check=True,capture_output=True)
 raw=subprocess.check_output(['ffmpeg','-v','error','-i',str(p),'-ac','1','-ar','4000','-f','f32le','-'])
 p.unlink();time.sleep(.2)
 return np.frombuffer(raw,dtype='<f4').astype(np.float64)

def compare(src,dst):
 rate=4000;n=rate*6
 cs=np.r_[0,np.cumsum(src)];sq=np.r_[0,np.cumsum(src*src)]
 energy=np.maximum(sq[n:]-sq[:-n]-(cs[n:]-cs[:-n])**2/n,1e-12)
 evidence=[]
 for a in range(0,len(dst)-n+1,rate*4):
  y=dst[a:a+n];y=y-y.mean();e=float(y@y)
  if e/n<1e-7:continue
  corr=np.abs(fftconvolve(src,y[::-1],mode='valid'))/np.sqrt(energy*e)
  k=int(np.argmax(corr));evidence.append({'targetStart':a/rate,'offset':round((k-a)/rate,5),'score':round(float(corr[k]),5)})
 if not evidence:return {'accepted':False,'reason':'no active windows','windows':[]}
 strong=[r for r in evidence if r['score']>=.65]
 offset=float(np.median([r['offset'] for r in strong])) if strong else 0
 good=[r for r in evidence if r['score']>=.65 and abs(r['offset']-offset)<=.02]
 coverage=len(good)/len(evidence);median=float(np.median([r['score'] for r in good])) if good else 0
 gaps=[b['targetStart']-a['targetStart'] for a,b in zip(good,good[1:])]
 consistent=coverage>=.9 and median>=.8 and len(good)>=10 and max(gaps,default=999)<=8 and good[0]['targetStart']<=12 and len(dst)/rate-good[-1]['targetStart']-6<=10
 # Different editing or unsupported tails cannot be represented by this constant map.
 consistent=consistent and abs((len(src)-len(dst))/rate-offset)<=2
 return {'accepted':bool(consistent),'reason':'verified constant offset' if consistent else 'insufficient full-recording waveform support or inconsistent edit','sourceMinusTarget':round(offset,5),'coverage':round(coverage,4),'medianScore':round(median,5),'duration':len(dst)/rate,'referenceDuration':len(src)/rate,'windows':evidence}

def main():
 work=Path(sys.argv[1]);mode=sys.argv[2]
 root=Path(__file__).resolve().parents[1]
 vocals=json.loads((work/'musicVocals.json').read_text())
 songs=[]
 for p in sorted((root/'lyrics').glob('*/lyrics.json')):
  d=json.loads(p.read_text());vs=[v for v in vocals if v['musicId']==d['musicId']]
  ref=next((v for v in vs if v['id']==d.get('vocalId') or v['assetbundleName']==d.get('assetbundle')),None)
  targets=[v for v in vs if v!=ref and v['id'] not in {x['vocalId'] for x in d.get('versions',[])}]
  if ref and targets:songs.append((d['musicId'],ref,targets))
 if mode=='pilot':songs=songs[:15]
 elif mode!='batch':raise ValueError(mode)
 path=work/f'audio-{mode}.json';results=json.loads(path.read_text()) if path.exists() else []
 done={r['vocalId'] for r in results}
 if mode == 'batch' and (work/'audio-pilot.json').exists():
  done.update(r['vocalId'] for r in json.loads((work/'audio-pilot.json').read_text()))
 lock=threading.Lock()
 def record(out):
  with lock:
   results.append(out)
   replacement=path.with_suffix('.tmp')
   replacement.write_text(json.dumps(results));replacement.replace(path)
   print(out['musicId'],out['vocalId'],out['accepted'],out.get('coverage'),out.get('medianScore'),flush=True)
 def process(song):
  mid,ref,targets=song
  targets=[v for v in targets if v['id'] not in done]
  if not targets:return
  with tempfile.TemporaryDirectory(prefix='audio-',dir=work) as temp:
   try:src=fetch(ref,Path(temp))
   except Exception as e:
    for v in targets:record({'musicId':mid,'vocalId':v['id'],'accepted':False,'reason':'reference download/decode failed: '+type(e).__name__})
    return
   for v in targets:
    out={'musicId':mid,'vocalId':v['id'],'referenceVocalId':ref['id'],'assetbundle':v['assetbundleName'],'source':'C' if len(v['characters'])==1 else 'D'}
    try:out.update(compare(src,fetch(v,Path(temp))))
    except Exception as e:out.update(accepted=False,reason='download/decode/mapping failed: '+type(e).__name__)
    record(out)
 with ThreadPoolExecutor(max_workers=1 if mode=='pilot' else 4) as pool:
  list(pool.map(process,songs))

if __name__ == '__main__':
 main()
