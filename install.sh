#!/usr/bin/env bash
# Install fiftyfm to /opt/fiftyfm with a weekly systemd timer. Run as root.
set -euo pipefail

APP_DIR=/opt/fiftyfm
ENV_FILE=/etc/fiftyfm/env
REPO_DIR="$(cd "$(dirname "$0")" && pwd)"
python_ok() {
    "$1" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' 2>/dev/null
}

# Without an explicit PYTHON, look for a >= 3.11 interpreter: first the one
# the existing install was built with (sudo's secure_path often hides it),
# then versioned names on PATH, then standalone builds under /opt/python.
if [[ -z "${PYTHON:-}" ]]; then
    candidates=()
    if [[ -f "$APP_DIR/.venv/pyvenv.cfg" ]]; then
        home="$(sed -n 's/^home *= *//p' "$APP_DIR/.venv/pyvenv.cfg")"
        [[ -n "$home" ]] && candidates+=("$home/python3")
    fi
    candidates+=(python3.14 python3.13 python3.12 python3.11)
    while IFS= read -r p; do
        candidates+=("$p")
    done < <(ls -d /opt/python/*/bin/python3 2>/dev/null | sort -rV)
    candidates+=(python3)
    for c in "${candidates[@]}"; do
        if python_ok "$c"; then
            PYTHON="$c"
            break
        fi
    done
fi

if [[ -z "${PYTHON:-}" ]] || ! python_ok "$PYTHON"; then
    echo "error: fiftyfm needs Python >= 3.11 and none was found." >&2
    echo "Install one (e.g. apt install python3.11 python3.11-venv via the" >&2
    echo "deadsnakes PPA on Ubuntu, or dnf install python3.11) and re-run, or" >&2
    echo "point at it by full path: sudo PYTHON=/path/to/python3.11 ./install.sh" >&2
    exit 1
fi

echo "Installing fiftyfm from $REPO_DIR to $APP_DIR using $PYTHON"
mkdir -p "$APP_DIR"
rm -rf "$APP_DIR/src"
cp -r "$REPO_DIR/src" "$REPO_DIR/pyproject.toml" "$APP_DIR/"
"$PYTHON" -m venv "$APP_DIR/.venv"
"$APP_DIR/.venv/bin/pip" install --quiet --upgrade "$APP_DIR"

if [[ ! -f "$ENV_FILE" ]]; then
    mkdir -p /etc/fiftyfm
    cat > "$ENV_FILE" <<'EOF'
SPOTIFY_CLIENT_ID=
SPOTIFY_CLIENT_SECRET=
SPOTIFY_REFRESH_TOKEN=
DISCORD_WEBHOOK_URL=
LASTFM_API_KEY=
EOF
    chmod 600 "$ENV_FILE"
    echo "Created $ENV_FILE - fill in your credentials (see README)."
fi

if ! grep -q '^LASTFM_API_KEY=' "$ENV_FILE"; then
    echo 'LASTFM_API_KEY=' >> "$ENV_FILE"
    echo "Added LASTFM_API_KEY to $ENV_FILE - fill it in (see README)."
fi

cp "$REPO_DIR/deploy/fiftyfm.service" "$REPO_DIR/deploy/fiftyfm.timer" \
   "$REPO_DIR/deploy/fiftyfm-poll.service" \
   "$REPO_DIR/deploy/fiftyfm-poll.timer" \
   /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now fiftyfm.timer fiftyfm-poll.timer
echo "Installed. Next run: $(systemctl list-timers fiftyfm.timer --no-pager | sed -n 2p)"
echo "Next poll: $(systemctl list-timers fiftyfm-poll.timer --no-pager | sed -n 2p)"
echo "Test with: $APP_DIR/.venv/bin/fiftyfm run --dry-run"
echo "       and: $APP_DIR/.venv/bin/fiftyfm poll --dry-run"
