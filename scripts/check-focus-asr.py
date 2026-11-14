"""Optional independent transcription for three disputed songs.
uv run --no-project --with faster-whisper==1.2.1 python scripts/check-focus-asr.py TEMP_DIRECTORY
Models and raw transcription stay outside the repository; audio is removed per song.
"""
import json,tempfile,subprocess,time,sys
from pathlib import Path
from faster_whisper import WhisperModel
import numpy as np
work=Path(sys.argv[1])
root=Path(__file__).resolve().parents[1]
model=WhisperModel('small',device='cpu',compute_type='int8',cpu_threads=2,num_workers=1,download_root=str(work/'models'))
comparisons=json.loads((root/'reports/timing-comparison.json').read_text());out=[]
for mid in [54,731,766]:
 s=next(s for s in comparisons['songs'] if s['musicId']==mid);asset=s['assetbundle']
 with tempfile.TemporaryDirectory(dir=work) as tmp:
  p=Path(tmp)/'audio.mp3'
  subprocess.run(['curl','-fsSL','--max-time','60',f'https://assets-direct.unipjsk.com/ondemand/music/long/{asset}/{asset}.mp3','-o',str(p)],check=True)
  audio=np.frombuffer(subprocess.check_output(['ffmpeg','-v','error','-i',str(p),'-ac','1','-ar','16000','-f','f32le','-']),dtype='<f4')
  segments,info=model.transcribe(audio,language='ja',beam_size=5,word_timestamps=True,condition_on_previous_text=False,vad_filter=False)
  result={'musicId':mid,'model':'faster-whisper small int8','segments':[]}
  for seg in segments:
   result['segments'].append({'start':seg.start,'end':seg.end,'text':seg.text,'avgLogprob':seg.avg_logprob,'words':[{'start':w.start,'end':w.end,'text':w.word,'probability':w.probability} for w in seg.words]})
  out.append(result);(work/'asr-focus.json').write_text(json.dumps(out,ensure_ascii=False,indent=2));print(mid,flush=True)
