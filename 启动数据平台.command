#!/bin/zsh
set -eu
cd "$(dirname "$0")"
./.venv/bin/python scripts/serve.py start
echo '打开 http://127.0.0.1:8765'
