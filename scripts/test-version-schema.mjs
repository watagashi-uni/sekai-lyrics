import assert from 'node:assert/strict'
import { validateVersions, defaultRows } from './version-schema.mjs'
const data = {duration:4,format:'lrc', lrc:'[00:02.00][00:01.00]あ\n[00:01.00]い', vocalId:1,
  versions:[{vocalId:2,assetbundle:'test',duration:4,source:'C',performers:[{performerId:'歌唱者-21',name:'初音ミク',characterId:21}],singers:[{row:0,performerIds:['歌唱者-21']},{row:2,segments:[{text:'あ',performerIds:['歌唱者-21']}]}]}]}
assert.deepEqual(defaultRows(data).map(l=>l.text),['あ','い','あ'])
validateVersions(data)
assert.equal(defaultRows({format:'lrc',duration:4,lrc:'[00:01]あ\n[00:02]\n[00:05]範囲外'})[0].end, 2)
for (const mutate of [d=>d.versions[0].singers[0].row=3,d=>d.versions[0].singers[0].performerIds=['unknown'],d=>d.versions[0].singers[0].start=1,d=>d.versions[0].singers[1].row=0,d=>d.versions[0].singers[1].segments[0].text='い',d=>d.versions[0].singers.push({row:1}),d=>d.versions[0].lines=[],d=>d.versions[0].vocalId=1]) {
  const copy=structuredClone(data);mutate(copy);assert.throws(()=>validateVersions(copy))
}
// Version lines become singers on the default rows: repeats by order and time, sentences broken differently joined.
const { unifyVersion } = await import('./unify-version-singers.mjs')
const song = {duration:30,format:'lrc',vocalId:1,lrc:'[00:01.00][00:10.00]サビ\n[00:05.00]A B',
  versions:[{vocalId:2,assetbundle:'x',duration:30,source:'A',performers:[{performerId:'歌唱者-21',name:'ミク',characterId:21},{performerId:'歌唱者-22',name:'リン',characterId:22}],credits:{translation:'t'},
    lines:[{textRef:0,start:0.5,end:4,performerIds:['歌唱者-21']},{text:'A',start:5.2,end:6,performerIds:['歌唱者-22']},{text:'B',start:6,end:7,performerIds:['歌唱者-21']},{textRef:0,start:10.3,end:12,segments:[{text:'サビ',performerIds:['歌唱者-22']}]},{text:'他',start:20,end:21,performerIds:['歌唱者-21']}]}]}
const unified = unifyVersion(song, song.versions[0])
assert.deepEqual(unified.version.singers, [
  {row:0,performerIds:['歌唱者-21']},
  {row:1,segments:[{text:'A ',performerIds:['歌唱者-22']},{text:'B',performerIds:['歌唱者-21']}]},
  {row:2,segments:[{text:'サビ',performerIds:['歌唱者-22']}]},
])
assert.deepEqual(unified.unmatched.map(u => u.text), ['他'])
assert.equal(unified.version.lines, undefined)
assert.equal(unified.version.credits, undefined)
validateVersions({...song, versions:[unified.version]})
console.log('version schema checks passed')
