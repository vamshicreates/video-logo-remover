#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RUNTIME_DIR="${SCRIPT_DIR}/.runtime"
PYTHON_BIN="${PYTHON:-python3}"

need_cv=0
setup_requested=0
if [[ "${1:-}" == "setup" ]]; then
  need_cv=1
  setup_requested=1
  shift
elif [[ "${1:-}" == "remove" ]]; then
  need_cv=1
  for arg in "$@"; do
    if [[ "$arg" == "--box" ]]; then
      need_cv=0
      break
    fi
  done
fi

if [[ "$need_cv" -eq 1 ]]; then
  if [[ ! -x "${RUNTIME_DIR}/bin/python" ]]; then
    echo "Preparing the private video-logo-remover runtime..." >&2
    "$PYTHON_BIN" -m venv "$RUNTIME_DIR"
  fi
  if ! "${RUNTIME_DIR}/bin/python" -c 'import cv2, numpy' >/dev/null 2>&1; then
    echo "Installing OpenCV and NumPy into the private runtime..." >&2
    "${RUNTIME_DIR}/bin/python" -m pip install --disable-pip-version-check -r "${SCRIPT_DIR}/requirements.txt"
  fi
  if [[ "$setup_requested" -eq 1 ]]; then
    echo "Runtime ready: ${RUNTIME_DIR}" >&2
    exit 0
  fi
  exec "${RUNTIME_DIR}/bin/python" "${SCRIPT_DIR}/video_logo_remover.py" "$@"
fi

exec "$PYTHON_BIN" "${SCRIPT_DIR}/video_logo_remover.py" "$@"
