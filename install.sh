#!/usr/bin/env bash
# Install fiftyfm to /opt/fiftyfm with a weekly systemd timer. Run as root.
set -euo pipefail

APP_DIR=/opt/fiftyfm
ENV_FILE=/etc/fiftyfm/env
REPO_DIR="$(cd "$(dirname "$0")" && pwd)"
PYTHON="${PYTHON:-python3}"

if ! "$PYTHON" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)'; then
    echo "error: fiftyfm needs Python >= 3.11; '$PYTHON' is $("$PYTHON" -V 2>&1)." >&2
    echo "Install a newer Python (e.g. apt install python3.11 python3.11-venv" >&2
    echo "via the deadsnakes PPA on Ubuntu, or dnf install python3.11) and" >&2
    echo "re-run as: PYTHON=python3.11 sudo -E ./install.sh" >&2
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
EOF
    chmod 600 "$ENV_FILE"
    echo "Created $ENV_FILE - fill in your credentials (see README)."
fi

cp "$REPO_DIR/deploy/fiftyfm.service" "$REPO_DIR/deploy/fiftyfm.timer" \
   /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now fiftyfm.timer
echo "Installed. Next run: $(systemctl list-timers fiftyfm.timer --no-pager | sed -n 2p)"
echo "Test with: $APP_DIR/.venv/bin/fiftyfm run --dry-run"
