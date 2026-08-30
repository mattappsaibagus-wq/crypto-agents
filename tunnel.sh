#!/usr/bin/env bash
# ⚡ Crypto Agent Team — public tunnel helper
#
# Gives your dashboard a public https:// URL so you can open it from anywhere,
# not just your home Wi-Fi. No account needed; the URL is random and
# temporary (changes each time you run this).
#
# Usage:
#   1) In one terminal:  python3 server.py           (keep it running)
#   2) In another:       ./tunnel.sh
#
# First run only: this needs the free Cloudflare tunnel client:
#     brew install cloudflared
#
set -e
PORT="${1:-8080}"

# Find cloudflared: on PATH, or installed locally
if command -v cloudflared >/dev/null 2>&1; then
  CF="cloudflared"
elif [ -x "$HOME/.local/bin/cloudflared" ]; then
  CF="$HOME/.local/bin/cloudflared"
else
  echo "❌ 'cloudflared' is not installed."
  echo "   Install it once with one of these, then run this script again:"
  echo "      brew install cloudflared"
  echo "      # or download the binary to ~/.local/bin/cloudflared"
  exit 1
fi

echo "🔗 Opening a temporary public tunnel to http://localhost:${PORT} ..."
echo "   Look for the https://<random>.trycloudflare.com line below."
echo "   Note: the URL changes every time you restart the tunnel."
echo ""
echo "   Press Ctrl+C to close the tunnel (your local server keeps running)."
echo ""
"$CF" tunnel --url "http://localhost:${PORT}"
