#!/usr/bin/env bash
# One-shot setup for the genmedia MCP servers (Veo, Omni, avtool) on this machine.
# Idempotent: safe to re-run. Installs pre-built Go binaries, checks ffmpeg,
# ensures the output bucket exists, and registers stdio servers with `agy mcp add`.
#
# Usage: scripts/setup.sh [--project PROJECT_ID] [--bucket BUCKET_NAME] [--no-config]
set -euo pipefail

PROJECT="${GOOGLE_CLOUD_PROJECT:-$(gcloud config get-value project 2>/dev/null)}"
BUCKET="${GENMEDIA_BUCKET:-${PROJECT}-genmedia}"
WRITE_CONFIG=1
while [[ $# -gt 0 ]]; do
  case "$1" in
    --project) PROJECT="$2"; shift 2 ;;
    --bucket)  BUCKET="$2";  shift 2 ;;
    --no-config) WRITE_CONFIG=0; shift ;;
    *) echo "unknown arg: $1"; exit 2 ;;
  esac
done
INSTALL_DIR="$HOME/.local/bin"
REPO="GoogleCloudPlatform/vertex-ai-creative-studio"
info() { printf '==> %s\n' "$*"; }

# 1. Binaries (pre-built, from the repo's mcp-v* GitHub releases)
if ls "$INSTALL_DIR"/mcp-veo-go "$INSTALL_DIR"/mcp-omni-go "$INSTALL_DIR"/mcp-avtool-go >/dev/null 2>&1; then
  info "genmedia binaries already installed in $INSTALL_DIR"
else
  OS="$(uname -s | tr '[:upper:]' '[:lower:]')"; ARCH="$(uname -m)"
  case "$ARCH" in x86_64) ARCH=amd64 ;; arm64|aarch64) ARCH=arm64 ;; esac
  TAG=$(curl -sL "https://api.github.com/repos/$REPO/releases" | grep '"tag_name": "mcp-v' | head -n1 | awk -F'"' '{print $4}')
  [[ -n "$TAG" ]] || { echo "could not find an mcp-v* release"; exit 1; }
  CLEAN=${TAG#mcp-}
  URL="https://github.com/$REPO/releases/download/v${CLEAN#v}/genmedia-mcp-servers_${OS}_${ARCH}.tar.gz"
  info "downloading $TAG from $URL"
  TMP=$(mktemp -d); trap 'rm -rf "$TMP"' EXIT
  curl -sL -f "$URL" -o "$TMP/g.tgz"; tar -xzf "$TMP/g.tgz" -C "$TMP"
  mkdir -p "$INSTALL_DIR"; mv "$TMP"/mcp-*-go "$INSTALL_DIR"/; chmod +x "$INSTALL_DIR"/mcp-*-go
  info "installed: $(ls "$INSTALL_DIR"/mcp-*-go | xargs -n1 basename | tr '\n' ' ')"
fi

# 2. ffmpeg (needed by mcp-avtool-go and for fps/format prep)
if command -v ffmpeg >/dev/null && command -v ffprobe >/dev/null; then
  info "ffmpeg present: $(ffmpeg -version | head -1 | cut -d' ' -f1-3)"
else
  info "installing ffmpeg via apt"
  sudo apt-get update -qq && sudo apt-get install -y -qq ffmpeg
fi

# 3. Auth + API + bucket
gcloud auth application-default print-access-token >/dev/null 2>&1 \
  || { echo "ADC missing: run 'gcloud auth application-default login'"; exit 1; }
gcloud services list --enabled --project "$PROJECT" 2>/dev/null | grep -q aiplatform.googleapis.com \
  || gcloud services enable aiplatform.googleapis.com --project "$PROJECT"
if gcloud storage buckets describe "gs://$BUCKET" --project "$PROJECT" >/dev/null 2>&1; then
  info "bucket gs://$BUCKET exists"
else
  info "creating gs://$BUCKET"
  gcloud storage buckets create "gs://$BUCKET" --project "$PROJECT" --location us-central1 --uniform-bucket-level-access
fi

# 4. Register stdio servers with Antigravity via `agy mcp add` (idempotent; re-adding updates)
if [[ $WRITE_CONFIG -eq 1 ]]; then
  command -v agy >/dev/null || { echo "agy CLI not found; install Antigravity CLI or re-run with --no-config"; exit 1; }
  for entry in "genmedia-veo:mcp-veo-go:us-central1" \
               "genmedia-omni:mcp-omni-go:global" \
               "genmedia-avtool:mcp-avtool-go:us-central1"; do
    IFS=: read -r name binary loc <<<"$entry"
    agy mcp add \
      --env "GOOGLE_CLOUD_PROJECT=$PROJECT" \
      --env "GENMEDIA_BUCKET=$BUCKET" \
      --env "GOOGLE_CLOUD_LOCATION=$loc" \
      "$name" "$INSTALL_DIR/$binary"
  done
fi

# 5. Smoke test
GOOGLE_CLOUD_PROJECT="$PROJECT" GENMEDIA_BUCKET="$BUCKET" \
  python3 "$(dirname "$0")/mcp_call.py" mcp-veo-go --list | head -3
info "done. Restart Antigravity (or refresh MCP servers) to pick up the new config."
