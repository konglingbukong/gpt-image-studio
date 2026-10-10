#!/usr/bin/env sh
# GPT Image Studio - start the local workbench in the background.
# If it's already running, this just opens the page.
DIR="$(cd "$(dirname "$0")" && pwd)"
nohup python3 "$DIR/web/server.py" >/dev/null 2>&1 &
