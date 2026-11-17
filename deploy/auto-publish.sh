#!/usr/bin/env bash
# Publish the newest commit of the GitHub branch to COS, once per commit.
# Installed as /data/watagashi/sekai-lyrics-publisher/auto-publish.sh and run every 10 minutes by
# sekai-lyrics-publish.timer. Cheap when idle: one `git ls-remote`, then exit.
#
# State (in $BASE): published-commit = last commit published, failed-commit = last commit
# that failed (not retried until a new push; delete the file to retry it).
# DRY_RUN=1 builds and compares against COS without uploading or recording state.
set -euo pipefail

BASE=${BASE:-/data/watagashi/sekai-lyrics-publisher}
SOURCE=${SOURCE:-https://github.com/watagashi-uni/sekai-lyrics.git}
BRANCH=${BRANCH:-main}
PYTHON=${PYTHON:-/data/watagashi/sekai-zh/.venv/bin/python}
REPO=$BASE/repo

exec 9>"$BASE/lock"
flock -n 9 || { echo "another run in progress"; exit 0; }

remote=$(git ls-remote "$SOURCE" "refs/heads/$BRANCH" | cut -f1)
[ -n "$remote" ] || { echo "branch $BRANCH not found at $SOURCE" >&2; exit 1; }
if [ -z "${DRY_RUN:-}" ]; then
  [ "$(cat "$BASE/published-commit" 2>/dev/null)" = "$remote" ] && exit 0
  [ "$(cat "$BASE/failed-commit" 2>/dev/null)" = "$remote" ] && exit 0
fi

fail() { [ -z "${DRY_RUN:-}" ] && echo "${commit:-$remote}" > "$BASE/failed-commit"; echo "publish of ${commit:-$remote} failed" >&2; }
trap fail ERR

[ -d "$REPO/.git" ] || git -c init.defaultBranch=main clone --quiet --no-checkout "$SOURCE" "$REPO"
git -C "$REPO" fetch --quiet "$SOURCE" "refs/heads/$BRANCH"
commit=$(git -C "$REPO" rev-parse FETCH_HEAD)
git -C "$REPO" checkout --quiet --force --detach "$commit"
git -C "$REPO" clean -fdxq
echo "building $commit ($(git -C "$REPO" log -1 --format=%s "$commit"))"

cd "$REPO"
node scripts/build-playback.mjs
node scripts/validate.mjs > /dev/null
git diff --quiet -- playback/version.json || echo "note: committed playback/ was not rebuilt; publishing the fresh build"
"$PYTHON" scripts/publish-cos.py ${DRY_RUN:+--dry-run}

trap - ERR
if [ -z "${DRY_RUN:-}" ]; then
  echo "$commit" > "$BASE/published-commit"
  rm -f "$BASE/failed-commit"
fi
