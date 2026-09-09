#!/usr/bin/env python3
import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

STATE = Path('/var/lib/ung-internalnet')
GEN = STATE / 'generated'
BACKUP = STATE / 'backup'
AP = os.getenv('UNG_INTERNALNET_AP_IFACE', 'wlan0')
UPLINK = os.getenv('UNG_INTERNALNET_UPLINK_IFACE', 'eth0')


def sh(*args, check=True, capture=False):
    return subprocess.run(args, check=check, text=True, capture_output=capture)


def require_root():
    if os.geteuid() != 0:
        sys.exit('Run with sudo/root')


def backup(path):
    p = Path(path)
    if p.exists():
        BACKUP.mkdir(parents=True, exist_ok=True)
        shutil.copy2(p, BACKUP / p.name)


def default_route():
    return sh('ip', 'route', 'show', 'default', check=False, capture=True).stdout.strip()


def preflight():
    missing = [x for x in ('hostapd', 'dnsmasq', 'nft', 'ip') if shutil.which(x) is None]
    if missing:
        sys.exit('Missing packages: ' + ', '.join(missing))
    if not Path(f'/sys/class/net/{AP}').exists():
        sys.exit(f'AP interface {AP} not found')
    if not Path(f'/sys/class/net/{UPLINK}').exists():
        sys.exit(f'Uplink interface {UPLINK} not found. Set UNG_INTERNALNET_UPLINK_IFACE to the real uplink before apply.')
    route = default_route()
    if f'dev {AP}' in route:
        sys.exit(f'REFUSED: {AP} is the current default-route interface. Connect a separate uplink before live activation.')
    if f'dev {UPLINK}' not in route:
        sys.exit(f'REFUSED: {UPLINK} is not the current default-route uplink. Current route: {route or "none"}')
    if not all((GEN / x).exists() for x in ('hostapd.conf', 'dnsmasq.conf', 'nftables.conf')):
        sys.exit('Generated configs missing; render them first')


def networkmanager_release_ap():
    if shutil.which('nmcli'):
        sh('nmcli', 'device', 'disconnect', AP, check=False)
        sh('nmcli', 'device', 'set', AP, 'managed', 'no', check=False)


def networkmanager_restore_ap():
    if shutil.which('nmcli'):
        sh('nmcli', 'device', 'set', AP, 'managed', 'yes', check=False)


def apply():
    require_root()
    preflight()
    backup('/etc/hostapd/hostapd.conf')
    backup('/etc/dnsmasq.d/ung-internalnet.conf')
    Path('/etc/hostapd').mkdir(parents=True, exist_ok=True)
    Path('/etc/dnsmasq.d').mkdir(parents=True, exist_ok=True)
    shutil.copy2(GEN / 'hostapd.conf', '/etc/hostapd/hostapd.conf')
    shutil.copy2(GEN / 'dnsmasq.conf', '/etc/dnsmasq.d/ung-internalnet.conf')

    networkmanager_release_ap()
    sh('systemctl', 'stop', 'hostapd', check=False)
    sh('systemctl', 'stop', 'dnsmasq', check=False)
    sh('ip', 'addr', 'flush', 'dev', AP)
    sh('ip', 'addr', 'add', '10.77.0.1/24', 'dev', AP)
    sh('ip', 'link', 'set', AP, 'up')

    Path('/etc/sysctl.d/90-ung-internalnet.conf').write_text('net.ipv4.ip_forward=1\n')
    sh('sysctl', '--system', check=False)

    sh('nft', 'delete', 'table', 'inet', 'ung_internalnet', check=False)
    sh('nft', 'delete', 'table', 'ip', 'ung_internalnet_nat', check=False)
    sh('nft', '-f', str(GEN / 'nftables.conf'))

    sh('systemctl', 'unmask', 'hostapd', check=False)
    sh('systemctl', 'enable', 'hostapd', check=False)
    sh('systemctl', 'restart', 'hostapd')
    sh('systemctl', 'restart', 'dnsmasq')

    hostapd_ok = sh('systemctl', 'is-active', '--quiet', 'hostapd', check=False).returncode == 0
    dnsmasq_ok = sh('systemctl', 'is-active', '--quiet', 'dnsmasq', check=False).returncode == 0
    if not (hostapd_ok and dnsmasq_ok):
        sys.exit(f'AP activation incomplete: hostapd={hostapd_ok} dnsmasq={dnsmasq_ok}')

    print('UNG-INTERNALNET LIVE')
    print(f'SSID={os.getenv("UNG_INTERNALNET_SSID", "InternalNet")}')
    print('GATEWAY=10.77.0.1')
    print(f'UPLINK={UPLINK}')


def rollback():
    require_root()
    sh('systemctl', 'stop', 'hostapd', check=False)
    sh('systemctl', 'stop', 'dnsmasq', check=False)
    sh('nft', 'delete', 'table', 'inet', 'ung_internalnet', check=False)
    sh('nft', 'delete', 'table', 'ip', 'ung_internalnet_nat', check=False)
    sh('ip', 'addr', 'flush', 'dev', AP, check=False)
    Path('/etc/sysctl.d/90-ung-internalnet.conf').unlink(missing_ok=True)
    sh('sysctl', '--system', check=False)
    for name, dst in [
        ('hostapd.conf', '/etc/hostapd/hostapd.conf'),
        ('ung-internalnet.conf', '/etc/dnsmasq.d/ung-internalnet.conf'),
    ]:
        src = BACKUP / name
        if src.exists():
            shutil.copy2(src, dst)
    networkmanager_restore_ap()
    sh('systemctl', 'restart', 'NetworkManager', check=False)
    print('UNG-INTERNALNET rollback completed')


p = argparse.ArgumentParser()
p.add_argument('--apply', action='store_true')
p.add_argument('--rollback', action='store_true')
a = p.parse_args()
if a.apply:
    apply()
elif a.rollback:
    rollback()
else:
    p.print_help()
