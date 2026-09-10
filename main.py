import json
import os
import secrets
import subprocess
import sys
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel

from internalnet_100 import APStatus, diagnose_network, phase1_plan

APP_VERSION = "1.2.0"
LIVE = os.getenv("UNG_INTERNALNET_LIVE", "0") == "1"
TOKEN = os.getenv("UNG_INTERNALNET_ADMIN_TOKEN", "")
AP_IFACE = os.getenv("UNG_INTERNALNET_AP_IFACE", "wlan0")
UPLINK_IFACE = os.getenv("UNG_INTERNALNET_UPLINK_IFACE", "eth0")
SSID = os.getenv("UNG_INTERNALNET_SSID", "InternalNet")
PASSPHRASE = os.getenv("UNG_INTERNALNET_PASSPHRASE", "")
STATE = Path("/var/lib/ung-internalnet")
GENERATED = STATE / "generated"
TELEMETRY_FILE = STATE / "internalnet100_telemetry.json"
INSTALLER = Path(__file__).resolve().with_name("pi_installer.py")

app = FastAPI(title="UNG-INTERNALNET", version=APP_VERSION)


class APTelemetry(BaseModel):
    ap_id: str
    online: bool = True
    clients: int = 0
    client_target: int = 50
    signal_dbm: Optional[int] = None
    packet_loss_pct: float = 0.0
    latency_ms: float = 0.0


class NetworkTelemetry(BaseModel):
    aps: list[APTelemetry]
    dhcp_used: int = 0
    dhcp_total: int = 151
    uplink_online: bool = True


def admin(authorization: str | None):
    if not TOKEN:
        raise HTTPException(503, "admin token not configured")
    supplied = (authorization or "").removeprefix("Bearer ").strip()
    if not secrets.compare_digest(supplied, TOKEN):
        raise HTTPException(401, "unauthorized")


def run(*args: str):
    p = subprocess.run(args, text=True, capture_output=True)
    if p.returncode:
        raise HTTPException(500, (p.stderr or p.stdout or "command failed").strip())
    return p.stdout.strip()


def render():
    if not PASSPHRASE or len(PASSPHRASE) < 8:
        raise HTTPException(503, "Wi-Fi passphrase must be configured and at least 8 characters")
    GENERATED.mkdir(parents=True, exist_ok=True)
    hostapd = f'''interface={AP_IFACE}\ndriver=nl80211\nssid={SSID}\nhw_mode=g\nchannel=6\nwmm_enabled=1\nauth_algs=1\nwpa=2\nwpa_passphrase={PASSPHRASE}\nwpa_key_mgmt=WPA-PSK\nrsn_pairwise=CCMP\n'''
    dnsmasq = f'''interface={AP_IFACE}\nbind-interfaces\ndhcp-range=10.77.0.50,10.77.0.200,255.255.255.0,12h\ndhcp-option=3,10.77.0.1\ndhcp-option=6,10.77.0.1\nserver=1.1.1.1\nserver=8.8.8.8\n'''
    nft = f'''table inet ung_internalnet {{\n chain forward {{ type filter hook forward priority 0; policy drop; iifname \"{AP_IFACE}\" oifname \"{UPLINK_IFACE}\" accept; iifname \"{UPLINK_IFACE}\" oifname \"{AP_IFACE}\" ct state established,related accept; }}\n}}\ntable ip ung_internalnet_nat {{\n chain postrouting {{ type nat hook postrouting priority 100; oifname \"{UPLINK_IFACE}\" masquerade; }}\n}}\n'''
    (GENERATED / "hostapd.conf").write_text(hostapd)
    (GENERATED / "dnsmasq.conf").write_text(dnsmasq)
    (GENERATED / "nftables.conf").write_text(nft)
    return {"rendered": True, "path": str(GENERATED)}


def _persist_telemetry(report: dict):
    try:
        STATE.mkdir(parents=True, exist_ok=True)
        TELEMETRY_FILE.write_text(json.dumps(report, indent=2))
    except Exception:
        pass


def _load_telemetry():
    if not TELEMETRY_FILE.exists():
        return {
            "system": "UNG-INTERNALNET",
            "phase": "InternalNet-100",
            "status": "not_reported",
            "alarm_count": 0,
            "alarms": [],
            "message": "No controller/AP telemetry has been reported yet",
        }
    try:
        return json.loads(TELEMETRY_FILE.read_text())
    except Exception:
        return {
            "system": "UNG-INTERNALNET",
            "phase": "InternalNet-100",
            "status": "telemetry_error",
            "alarm_count": 1,
            "alarms": [],
        }


@app.get("/")
def root():
    return {"system":"UNG-INTERNALNET","version":APP_VERSION,"ssid":SSID,"live_enabled":LIVE}


@app.get("/health")
def health():
    telemetry = _load_telemetry()
    return {
        "status":"ok",
        "system":"UNG-INTERNALNET",
        "version":APP_VERSION,
        "internalnet100_status": telemetry.get("status"),
        "diagnostic_alarm_count": telemetry.get("alarm_count", 0),
    }


@app.get("/api/network/status")
def status():
    def active(unit: str) -> bool:
        try:
            return subprocess.run(["systemctl","is-active","--quiet",unit]).returncode == 0
        except OSError:
            return False
    addr = subprocess.run(["ip","-4","addr","show","dev",AP_IFACE], text=True, capture_output=True)
    return {
        "ssid": SSID,
        "ap_interface": AP_IFACE,
        "uplink_interface": UPLINK_IFACE,
        "live_enabled": LIVE,
        "hostapd_active": active("hostapd"),
        "dnsmasq_active": active("dnsmasq"),
        "ap_address_present": "10.77.0.1/24" in addr.stdout,
    }


@app.get("/api/capacity/plan")
def capacity_plan():
    return phase1_plan()


@app.get("/api/telemetry/current")
def telemetry_current():
    return _load_telemetry()


@app.post("/api/telemetry/evaluate")
def telemetry_evaluate(body: NetworkTelemetry):
    aps = [APStatus(**ap.model_dump()) for ap in body.aps]
    return diagnose_network(aps, body.dhcp_used, body.dhcp_total, body.uplink_online)


@app.post("/api/telemetry/report")
def telemetry_report(body: NetworkTelemetry, authorization: str | None = Header(default=None)):
    admin(authorization)
    aps = [APStatus(**ap.model_dump()) for ap in body.aps]
    report = diagnose_network(aps, body.dhcp_used, body.dhcp_total, body.uplink_online)
    _persist_telemetry(report)
    return report


@app.post("/api/network/render")
def network_render(authorization: str | None = Header(default=None)):
    admin(authorization)
    return render()


@app.post("/api/network/apply")
def network_apply(authorization: str | None = Header(default=None)):
    admin(authorization)
    if not LIVE:
        raise HTTPException(409, "live mode disabled; set UNG_INTERNALNET_LIVE=1")
    render()
    if not INSTALLER.exists():
        raise HTTPException(500, "pi_installer.py not found")
    output = run(sys.executable, str(INSTALLER), "--apply")
    return {"status":"applied","ssid":SSID,"gateway":"10.77.0.1","output":output}


@app.post("/api/network/rollback")
def network_rollback(authorization: str | None = Header(default=None)):
    admin(authorization)
    if not INSTALLER.exists():
        raise HTTPException(500, "pi_installer.py not found")
    output = run(sys.executable, str(INSTALLER), "--rollback")
    return {"status":"rolled_back","output":output}
