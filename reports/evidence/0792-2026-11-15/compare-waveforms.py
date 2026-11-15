import numpy as np, subprocess,json
from scipy.signal import fftconvolve
from pathlib import Path
import sys
w=Path(sys.argv[1]);rate=4000

def read(n):return np.frombuffer(subprocess.check_output(['ffmpeg','-v','error','-i',str(w/n),'-ac','1','-ar',str(rate),'-f','f32le','-']),dtype='<f4').astype(float)
s=read('source.mp3');g=read('game.mp3');n=rate*4
cs=np.r_[0,np.cumsum(s)];sq=np.r_[0,np.cumsum(s*s)];energy=np.maximum(sq[n:]-sq[:-n]-(cs[n:]-cs[:-n])**2/n,1e-12)
rows=[]
for a in np.arange(2,122,2):
 y=g[int(a*rate):int(a*rate)+n];y-=y.mean();c=np.abs(fftconvolve(s,y[::-1],mode='valid'))/np.sqrt(energy*(y@y));k=int(c.argmax());rows.append({'gameStart':float(a),'sourceStart':k/rate,'offset':k/rate-float(a),'score':float(c[k])})
(w/'waveform-check.json').write_text(json.dumps(rows,indent=2))
for r in rows:print(round(r['gameStart'],2),round(r['offset'],3),round(r['score'],3))
