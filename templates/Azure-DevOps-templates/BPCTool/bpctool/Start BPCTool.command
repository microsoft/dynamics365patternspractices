#!/bin/bash
# Double-click launcher for macOS Finder.
set -euo pipefail
cd "$(dirname "$0")"

echo "=== BPCTool ==="
echo "Preparing environment (first launch may take a minute)..."
node scripts/ensure-env.mjs

echo ""
echo "Starting BPCTool (UI + local runner)..."
echo "A browser window should open shortly. Leave this window open while you work."
echo "Close this window to stop the app."
echo ""

npm start
