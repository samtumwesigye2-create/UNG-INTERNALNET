#!/usr/bin/env python3
import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

STATE=Path('/var/lib/ung-internalnet')
GEN=STATE/'generated'
BACKUP=STATE/'backup'
AP=os.getenv('UNG_INTERNALNET_AP_IFACE','wlan0')
UPLINK=os.getenv('UNG_INTERNALNET_UPLINK_IFACE','eth0')

def sh(*args, check=True):
    return subprocess.run(args, check=check, text=True)

def require_root():
    if os.geteuid()!=0:
        sys.exit('Run with sudo/root')

def backup(path):
    p=Path(path)
    if p.exists():
        BACKUP.mkdir(parents=True, exist_ok=True)
        shutil.copy2(p, BACKUP/p.name)

def preflight():
    missing=[x for x in ('hostapd','dnsmasq','nft') if shutil.which(x) is None]
    if missing:
        sys.exit('Missing packages: '+', '.join(missing))
    if not Path(f'/sys/class/net/{AP}').exists():
        sys.exit(f'AP interface {AP} not found')
    if not Path(f'/sys/class/net/{UPLINK}').exists():
        sys.exit(f'Uplink interface {UPLINK} not found. Set UNG_INTERNALNET_UPLINK_IFACE to the real uplink before apply.')
    if not all((GEN/x).exists() for x in ('hostapd.conf','dnsmasq.conf','nftables.conf')):
        sys.exit('Generated configs missing; render them first')

def apply():
    require_root(); preflight()
    # Refuse the dangerous single-radio case: if the AP interface owns the current default route,
    # converting it to AP mode can sever SSH. Use Ethernet/USB as uplink first.
    route=subprocess.run(['ip','route','show','default'],capture_output=True,text=True).stdout
    if f'dev {AP}' in route:
        sys.exit(f'REFUSED: {AP} is the current default-route interface. Connect a separate uplink (recommended Ethernet) before live activation.')
    backup('/etc/hostapd/hostapd.conf'); backup('/etc/dnsmasq.d/ung-internalnet.conf')
    Path('/etc/hostapd').mkdir(parents=True,exist_ok=True)
    Path('/etc/dnsmasq.d').mkdir(parents=True,exist_ok=True)
    shutil.copy2(GEN/'hostapd.conf','/etc/hostapd/hostapd.conf')
    shutil.copy2(GEN/'dnsmasq.conf','/etc/dnsmasq.d/ung-internalnet.conf')
    sh('ip','addr','flush','dev',AP)
    sh('ip','addr','add','10.77.0.1/24','dev',AP)
    sh('ip','link','set',AP,'up')
    Path('/proc/sys/net/ipv4/ip_forward').write_text('1\n')
    sh('nft','-f',str(GEN/'nftables.conf'))
    sh('systemctl','unmask','hostapd',check=False)
    sh('systemctl','enable','--now','hostapd')
    sh('systemctl','restart','dnsmasq')
    print('UNG-INTERNALNET live AP applied successfully')

def rollback():
    require_root()
    sh('systemctl','stop','hostapd',check=False)
    sh('systemctl','stop','dnsmasq',check=False)
    sh('nft','delete','table','inet','ung_internalnet',check=False)
    sh('nft','delete','table','ip','ung_internalnet_nat',check=False)
    for name,dst in [('hostapd.conf','/etc/hostapd/hostapd.conf'),('ung-internalnet.conf','/etc/dnsmasq.d/ung-internalnet.conf')]:
        src=BACKUP/name
        if src.exists(): shutil.copy2(src,dst)
    print('UNG-INTERNALNET rollback completed')

p=argparse.ArgumentParser()
p.add_argument('--apply',action='store_true'); p.add_argument('--rollback',action='store_true')
a=p.parse_args()
if a.apply: apply()
elif a.rollback: rollback()
else: p.print_help()
