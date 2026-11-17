#!/usr/bin/env python3
"""Publish playback/ to COS incrementally: only songs whose hash differs from the live index.

The live `lyrics/version.json` on COS is the baseline, so no saved "previous version" file
is needed. Each changed `<musicId>.<hash>.json` is uploaded (brotli, immutable) and read
back; `version.json` is written last, so clients never see a hash whose file is missing.
Published hash files are never overwritten or deleted, so clients holding an older index
keep working.

Run on the maintenance server after `node scripts/build-playback.mjs`:

    <python with boto3+brotli> scripts/publish-cos.py --dry-run
    <python with boto3+brotli> scripts/publish-cos.py               # everything changed
    <python with boto3+brotli> scripts/publish-cos.py --only 1,226  # just these songs

The COS client comes from sekai_zh.publish.client() (path: $SEKAI_ZH_ROOT, default
/data/watagashi/sekai-zh); this script never reads or prints the credentials itself.
"""
import argparse
import hashlib
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import brotli

ROOT = Path(__file__).resolve().parent.parent
PREFIX = 'lyrics/'
CONTENT_TYPE = 'application/json; charset=utf-8'
IMMUTABLE = 'public, max-age=31536000, immutable'
# The index is ~8 KB compressed: always revalidate (ETag -> 304) so a publish shows on next load.
INDEX_CACHE = 'no-cache'


def cos_client():
    sys.path.insert(0, os.environ.get('SEKAI_ZH_ROOT', '/data/watagashi/sekai-zh'))
    from sekai_zh.publish import client
    return client()


def read_object(s3, bucket, key):
    """Body of an object as stored, decoded if it was uploaded brotli-encoded; None if absent."""
    try:
        obj = s3.get_object(Bucket=bucket, Key=key)
    except s3.exceptions.NoSuchKey:
        return None
    body = obj['Body'].read()
    return brotli.decompress(body) if obj.get('ContentEncoding') == 'br' else body


def exists(s3, bucket, key):
    try:
        s3.head_object(Bucket=bucket, Key=key)
        return True
    except s3.exceptions.ClientError as error:
        if error.response.get('Error', {}).get('Code') in ('404', 'NoSuchKey', 'NotFound'):
            return False
        raise


def put(s3, bucket, key, raw, cache_control):
    body = brotli.compress(raw, quality=11)
    s3.put_object(Bucket=bucket, Key=key, Body=body, ContentType=CONTENT_TYPE,
                  ContentEncoding='br', CacheControl=cache_control)
    if s3.get_object(Bucket=bucket, Key=key)['Body'].read() != body:
        raise RuntimeError(f'read-back mismatch: {key}')
    return len(body)


def main():
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    parser.add_argument('--playback', type=Path, default=ROOT / 'playback', help='built playback directory')
    parser.add_argument('--only', help='comma-separated music ids; other songs keep their live hash')
    parser.add_argument('--allow-remove', action='store_true', help='drop live songs missing locally from the index')
    parser.add_argument('--dry-run', action='store_true', help='compare and report, upload nothing')
    args = parser.parse_args()

    local_raw = (args.playback / 'version.json').read_bytes()
    local = json.loads(local_raw)['songs']
    s3, bucket = cos_client()
    live_raw = read_object(s3, bucket, PREFIX + 'version.json')
    live = json.loads(live_raw)['songs'] if live_raw else {}

    if args.only:
        wanted = [mid.strip() for mid in args.only.split(',') if mid.strip()]
        missing = [mid for mid in wanted if mid not in local]
        if missing:
            sys.exit(f'not in local playback/version.json: {", ".join(missing)}')
        target = dict(live)
        target.update({mid: local[mid] for mid in wanted})
    else:
        removed = sorted(set(live) - set(local), key=int)
        if removed and not args.allow_remove:
            sys.exit(f'live index has songs missing locally ({", ".join(removed)}); pass --allow-remove to drop them')
        target = local

    changed = sorted((mid for mid, h in target.items() if live.get(mid) != h), key=int)
    dropped = sorted(set(live) - set(target), key=int)
    for mid in changed:
        name = f'{mid}.{target[mid]}.json'
        raw = (args.playback / name).read_bytes()
        if hashlib.sha256(raw).hexdigest()[:16] != target[mid]:
            sys.exit(f'{name}: content does not match its hash; rebuild playback first')

    report = {'bucket': bucket, 'liveSongs': len(live), 'targetSongs': len(target),
              'changedSongs': changed, 'droppedSongs': dropped, 'dryRun': args.dry_run}
    if args.dry_run or not (changed or dropped):
        report['uploaded'] = 0
        print(json.dumps(report, ensure_ascii=False))
        return

    def upload(mid):
        key = f'{PREFIX}{mid}.{target[mid]}.json'
        if exists(s3, bucket, key):  # same hash = same bytes; never overwrite
            return 0, 0
        return 1, put(s3, bucket, key, (args.playback / f'{mid}.{target[mid]}.json').read_bytes(), IMMUTABLE)

    with ThreadPoolExecutor(12) as pool:
        results = list(pool.map(upload, changed))
    index_raw = local_raw if target is local else json.dumps(
        {'v': 1, 'songs': {mid: target[mid] for mid in sorted(target, key=int)}}, separators=(',', ':')).encode()
    put(s3, bucket, PREFIX + 'version.json', index_raw, INDEX_CACHE)
    report.update(uploaded=sum(n for n, _ in results), alreadyPresent=len(changed) - sum(n for n, _ in results),
                  compressedBytes=sum(b for _, b in results), indexUpdated=True)
    print(json.dumps(report, ensure_ascii=False))


if __name__ == '__main__':
    main()
