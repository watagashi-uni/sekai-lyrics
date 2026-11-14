import assert from 'node:assert/strict'
import { validateVersions, defaultRows } from './version-schema.mjs'
const data = {duration:4,format:'lrc', lrc:'[00:02.00][00:01.00]あ\n[00:01.00]い', vocalId:1,
  versions:[{vocalId:2,assetbundle:'test',duration:4,source:'C',performers:[{performerId:'歌唱者-21',name:'初音ミク',characterId:21}],lines:[{textRef:0,start:1,end:2,performerIds:['歌唱者-21']},{textRef:1,start:1,end:2}]}]}
assert.deepEqual(defaultRows(data).map(l=>l.text),['あ','い','あ'])
validateVersions(data)
assert.equal(defaultRows({format:'lrc',duration:4,lrc:'[00:01]あ\n[00:02]\n[00:05]範囲外'})[0].end, 2)
for (const mutate of [d=>d.versions[0].lines[0].textRef=3,d=>d.versions[0].lines[0].performerIds=['unknown'],d=>d.versions[0].lines[1].start=0,d=>d.versions[0].lines[1].end=5,d=>d.versions[0].vocalId=1]) {
  const copy=structuredClone(data);mutate(copy);assert.throws(()=>validateVersions(copy))
}
console.log('version schema checks passed')
