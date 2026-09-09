#!/usr/bin/env bash
set -euo pipefail

AP=${UNG_INTERNALNET_AP_IFACE:-wlan0}
UPLINK=${UNG_INTERNALNET_UPLINK_IFACE:-eth0}
ROOT=/opt/ung-internalnet
ENV=/etc/ung-internalnet.env

if [ "$(id -u)" -ne 0 ]; then
  exec sudo -E bash "$0" "$@"
fi

if ! command -v nmcli >/dev/null 2>&1; then
  apt-get update
  apt-get install -y network-manager
fi

if [ ! -e "/sys/class/net/$UPLINK" ]; then
  echo "ERROR: uplink interface $UPLINK not found"
  exit 1
fi
if [ ! -e "/sys/class/net/$AP" ]; then
  echo "ERROR: AP interface $AP not found"
  exit 1
fi

carrier=$(cat "/sys/class/net/$UPLINK/carrier" 2>/dev/null || echo 0)
if [ "$carrier" != "1" ]; then
  echo "ERROR: Ethernet link is not active on $UPLINK. Check cable/router LAN port."
  exit 1
fi

nmcli device connect "$UPLINK" >/dev/null 2>&1 || true
sleep 3
ETH_CONN=$(nmcli -g GENERAL.CONNECTION device show "$UPLINK" | head -n1 || true)
WIFI_CONN=$(nmcli -g GENERAL.CONNECTION device show "$AP" | head -n1 || true)

if [ -n "$ETH_CONN" ] && [ "$ETH_CONN" != "--" ]; then
  nmcli connection modify "$ETH_CONN" ipv4.route-metric 50 ipv6.route-metric 50 || true
  nmcli connection up "$ETH_CONN" >/dev/null 2>&1 || true
fi
if [ -n "$WIFI_CONN" ] && [ "$WIFI_CONN" != "--" ]; then
  nmcli connection modify "$WIFI_CONN" ipv4.route-metric 600 ipv6.route-metric 600 || true
fi
sleep 3

if ! ip route show default | grep -q "dev $UPLINK"; then
  echo "ERROR: Ethernet did not become the default route. Current default route:"
  ip route show default
  exit 1
fi

if [ -f "$ENV" ]; then
  set -a
  . "$ENV"
  set +a
fi

cd "$ROOT"
./venv/bin/python -c 'import main; print(main.render())'
./venv/bin/python pi_installer.py --apply

echo "===== UNG-INTERNALNET LIVE ====="
echo "SSID=${UNG_INTERNALNET_SSID:-InternalNet}"
echo "GATEWAY=10.77.0.1"
echo "UPLINK=$UPLINK"
systemctl is-active hostapd || true
systemctl is-active dnsmasq || true
systemctl is-active ung-internalnet || true
