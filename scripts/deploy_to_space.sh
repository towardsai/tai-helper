#!/usr/bin/env bash
#
# Deploy this repository to the Hugging Face Space that serves the helper.
#
# The Space is a separate git repository from GitHub: merging to main does not
# change what visitors see until a snapshot is pushed here. Its history is a
# linear series of "Deploy tai-helper <sha>" commits, which this script extends.
#
# Usage:
#   HF_TOKEN=hf_... scripts/deploy_to_space.sh
#
# Environment:
#   HF_TOKEN       required, write-scoped token for the Space
#   HF_SPACE_REPO  optional, defaults to towardsai-tutors/tai_helper

set -euo pipefail

SPACE_REPO="${HF_SPACE_REPO:-towardsai-tutors/tai_helper}"
: "${HF_TOKEN:?HF_TOKEN must be set}"

SOURCE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REVISION="$(git -C "$SOURCE_DIR" rev-parse --short HEAD)"

WORKDIR="$(mktemp -d)"
cleanup() { rm -rf "$WORKDIR"; }
trap cleanup EXIT

echo "Cloning Space ${SPACE_REPO}..."
git clone --quiet --depth 1 \
  "https://user:${HF_TOKEN}@huggingface.co/spaces/${SPACE_REPO}" \
  "$WORKDIR/space"

# Mirror the repo into the Space. .gitattributes is excluded so the Space keeps
# its own LFS configuration, which does not exist on the GitHub side; excluded
# paths are also protected from --delete.
rsync -a --delete \
  --exclude '.git/' \
  --exclude '.gitattributes' \
  --exclude '.env' \
  --exclude '.venv/' \
  --exclude '__pycache__/' \
  --exclude '.pytest_cache/' \
  --exclude '.ruff_cache/' \
  --exclude '*.egg-info/' \
  --exclude 'uv.lock' \
  --exclude '.DS_Store' \
  "$SOURCE_DIR"/ "$WORKDIR/space"/

cd "$WORKDIR/space"

if [ -z "$(git status --porcelain)" ]; then
  echo "Space already matches ${REVISION}; nothing to deploy."
  exit 0
fi

echo "Changes to deploy:"
git status --porcelain

git add -A
git -c user.name="towards-ai-deploy" \
    -c user.email="deploy@towardsai.com" \
    commit --quiet -m "Deploy tai-helper ${REVISION}"

git push --quiet
echo "Deployed tai-helper ${REVISION} to ${SPACE_REPO}."
