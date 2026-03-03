#!/usr/bin/env bash
set -euo pipefail

export PYTHONPATH=src
uvicorn sentinel_api.main:app --reload --host 0.0.0.0 --port 8000
