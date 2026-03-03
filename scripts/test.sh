#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"

if [[ ! -d .venv ]]; then
  python3 -m venv .venv
fi

source .venv/bin/activate
python -m pip install --upgrade pip
pip install -e '.[dev]'

export SENTINEL_API_JWT_SECRET_KEY="${SENTINEL_API_JWT_SECRET_KEY:-test-secret}"

pytest -q
