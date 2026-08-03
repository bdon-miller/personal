#!/usr/bin/env bash
# Install fiftyfm to /opt/fiftyfm with a weekly systemd timer. Run as root.
set -euo pipefail

APP_DIR=/opt/fiftyfm
ENV_FILE=/etc/fiftyfm/env
REPO_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "Installing fiftyfm from $REPO_DIR to $APP_DIR"
mkdir -p "$APP_DIR"
rm -rf "$APP_DIR/src"
cp -r "$REPO_DIR/src" "$REPO_DIR/pyproject.toml" "$APP_DIR/"
python3 -m venv "$APP_DIR/.venv"
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
