#!/bin/zsh
set -e
cd "${0:A:h}"
if curl -fsS --max-time 1 http://127.0.0.1:8864/api/state >/dev/null 2>&1; then
    open http://127.0.0.1:8864
    exit 0
fi
if [[ -n "${WFS_PYTHON:-}" ]]; then
    viewer_python="$WFS_PYTHON"
elif [[ -x .venv/bin/python ]]; then
    viewer_python="$PWD/.venv/bin/python"
elif [[ -f runtime/python_path ]]; then
    viewer_python="$(<runtime/python_path)"
else
    viewer_python="python3"
fi
"$viewer_python" -c 'import flask, numpy, scipy, PIL' || {
    print -u2 "Missing dependencies. Follow the Python setup in README.md."
    exit 1
}
open http://127.0.0.1:8864
exec "$viewer_python" gui/app.py
