#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

mkdir -p .tmp

if ! command -v python >/dev/null 2>&1; then
  echo "Python is not available on PATH inside this container."
  exit 1
fi

REQUIREMENTS_FINGERPRINT_FILE=".tmp/runtime_requirements.sha256"
CURRENT_FINGERPRINT="$(
  {
    sha256sum requirements.txt
    sha256sum pyproject.toml
  } | sha256sum | awk '{print $1}'
)"
INSTALLED_FINGERPRINT="$(cat "$REQUIREMENTS_FINGERPRINT_FILE" 2>/dev/null || true)"

if [[ "$CURRENT_FINGERPRINT" != "$INSTALLED_FINGERPRINT" ]]; then
  echo "Installing or refreshing bot dependencies..."
  python -m pip install --disable-pip-version-check --no-cache-dir -U pip
  python -m pip install --disable-pip-version-check --no-cache-dir .
  printf '%s' "$CURRENT_FINGERPRINT" > "$REQUIREMENTS_FINGERPRINT_FILE"
fi

echo "Starting Highlight Manager..."
exec python -m highlight_manager
