#!/usr/bin/env bash
set -euo pipefail

REPO_URL="https://github.com/samtumwesigye2-create/UNG-INTERNALNET.git"
APP_DIR="/opt/ung-internalnet"
ENV_FILE="/etc/ung-internalnet.env"
SERVICE_FILE="/etc/systemd/system/ung-internalnet.service"

sudo apt-get update
sudo apt-get install -y hostapd dnsmasq nftables git python3-venv network-manager

sudo rm -rf "$APP_DIR"
sudo git clone "$REPO_URL" "$APP_DIR"
sudo python3 -m venv "$APP_DIR/venv"
sudo "$APP_DIR/venv/bin/pip" install -q -r "$APP_DIR/requirements.txt"

sudo tee "$ENV_FILE" >/dev/null <<'EOF'
UNG_INTERNALNET_LIVE=1
UNG_INTERNALNET_AP_IFACE=wlan0
UNG_INTERNALNET_UPLINK_IFACE=eth0
UNG_INTERNALNET_SSID=InternalNet
UNG_INTERNALNET_PASSPHRASE=uganda@future
UNG_INTERNALNET_ADMIN_TOKEN=UNG-LOCAL-ADMIN-2026
EOF

sudo cp "$APP_DIR/ung-internalnet.service" "$SERVICE_FILE"
sudo systemctl daemon-reload
sudo systemctl enable --now ung-internalnet

set -a
source "$ENV_FILE"
set +a
cd "$APP_DIR"
sudo -E "$APP_DIR/venv/bin/python" -c 'import main; main.render()'
sudo -E "$APP_DIR/venv/bin/python" "$APP_DIR/pi_installer.py" --apply

echo "===== UNG-INTERNALNET LIVE ====="
echo "SSID=InternalNet"
echo "GATEWAY=10.77.0.1"
echo "UPLINK=eth0"
systemctl is-active ung-internalnet hostapd dnsmasq
ip -br addr show wlan0
