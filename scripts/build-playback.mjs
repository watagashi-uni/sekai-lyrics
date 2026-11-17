import { validateVersions } from './version-schema.mjs'
import { readFile, writeFile, mkdir, readdir, unlink } from 'node:fs/promises'
import { createHash } from 'node:crypto'
import { fileURLToPath } from 'node:url'
import path from 'node:path'

const root = fileURLToPath(new URL('../', import.meta.url))
const output = path.join(root, 'playback')
await mkdir(output, { recursive: true })
const songs = {}
for (const folder of (await readdir(path.join(root, 'lyrics'))).sort()) {
  if (!/^\d+$/.test(folder)) continue
  const body = await readFile(path.join(root, 'lyrics', folder, 'lyrics.json'))
  const data = JSON.parse(body)
  validateVersions(data)
  if (data.musicId !== Number(folder) || !Number.isFinite(data.duration)) throw new Error(`Invalid song ${folder}`)
  const hash = createHash('sha256').update(body).digest('hex').slice(0, 16)
  songs[data.musicId] = hash
  await writeFile(path.join(output, `${data.musicId}.${hash}.json`), body)
}
// Publish this pointer only after all of its immutable song files are available.
await writeFile(path.join(output, 'version.json'), JSON.stringify({ v: 1, songs }))
// Older hashes stay on COS for clients holding an older index; the repo keeps only the current set.
const current = new Set(Object.entries(songs).map(([mid, hash]) => `${mid}.${hash}.json`))
let removed = 0
for (const name of await readdir(output)) {
  if (/^\d+\.[a-f0-9]{16}\.json$/.test(name) && !current.has(name)) {
    await unlink(path.join(output, name))
    removed++
  }
}
console.log(`Built ${Object.keys(songs).length} playback resources, removed ${removed} stale`)
