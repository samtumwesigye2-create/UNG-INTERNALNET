"""UNG-INTERNALNET Phase 1 capacity/control model for ~100 users.
Non-destructive: this module models APs, VLANs, capacity and diagnostic alarms; it does not rewrite hostapd/network config.
"""
from dataclasses import dataclass, asdict
from typing import Optional

SYSTEM_CODE = "802"

DCODES = {
    "000": ("healthy", "normal"),
    "201": ("access point offline", "critical"),
    "302": ("access point over capacity", "high"),
    "303": ("network user capacity high", "high"),
    "304": ("weak radio signal", "medium"),
    "421": ("DHCP pool above 80 percent", "high"),
    "503": ("internet uplink down", "critical"),
    "611": ("high packet loss", "high"),
    "612": ("high latency", "medium"),
}

VLANS = {
    "management": {"vlan": 10, "subnet": "10.77.10.0/24"},
    "operations": {"vlan": 20, "subnet": "10.77.20.0/24"},
    "staff": {"vlan": 30, "subnet": "10.77.30.0/24"},
    "iot": {"vlan": 40, "subnet": "10.77.40.0/24"},
    "guest": {"vlan": 50, "subnet": "10.77.50.0/24"},
}

@dataclass
class APStatus:
    ap_id: str
    online: bool = True
    clients: int = 0
    client_target: int = 50
    signal_dbm: Optional[int] = None
    packet_loss_pct: float = 0.0
    latency_ms: float = 0.0


def alarm(fault: str, location: str, detail: str):
    text, severity = DCODES[fault]
    canonical = f"D-{SYSTEM_CODE}-{fault}"
    return {
        "d_code": canonical,
        "code": canonical,
        "legacy_u_code": f"U-{SYSTEM_CODE}-{fault}",
        "system": "UNG-INTERNALNET",
        "system_number": SYSTEM_CODE,
        "location": location,
        "fault_number": fault,
        "fault": text,
        "severity": severity,
        "detail": detail,
    }


def diagnose_ap(ap: APStatus):
    out = []
    if not ap.online:
        return [alarm("201", ap.ap_id, "AP is not responding")]
    if ap.clients > ap.client_target:
        out.append(alarm("302", ap.ap_id, f"{ap.clients} clients; target <= {ap.client_target}"))
    if ap.signal_dbm is not None and ap.signal_dbm < -70:
        out.append(alarm("304", ap.ap_id, f"signal {ap.signal_dbm} dBm"))
    if ap.packet_loss_pct >= 5:
        out.append(alarm("611", ap.ap_id, f"packet loss {ap.packet_loss_pct:.1f}%"))
    if ap.latency_ms >= 100:
        out.append(alarm("612", ap.ap_id, f"latency {ap.latency_ms:.0f} ms"))
    return out


def diagnose_network(aps, dhcp_used: int, dhcp_total: int, uplink_online: bool = True):
    alarms = []
    for ap in aps:
        alarms.extend(diagnose_ap(ap))
    clients = sum(a.clients for a in aps if a.online)
    target = sum(a.client_target for a in aps)
    if target and clients >= int(target * 0.8):
        alarms.append(alarm("303", "InternalNet", f"{clients}/{target} planned client capacity in use"))
    if dhcp_total and dhcp_used / dhcp_total >= .8:
        alarms.append(alarm("421", "DHCP", f"{dhcp_used}/{dhcp_total} leases in use"))
    if not uplink_online:
        alarms.append(alarm("503", "WAN", "internet uplink unavailable"))
    return {
        "system": "UNG-INTERNALNET",
        "system_number": SYSTEM_CODE,
        "phase": "InternalNet-100",
        "users": clients,
        "planned_capacity": target,
        "aps": [asdict(a) for a in aps],
        "vlans": VLANS,
        "status": "healthy" if not alarms else "degraded",
        "alarm_count": len(alarms),
        "alarms": alarms,
    }


def phase1_plan():
    return {
        "name": "InternalNet-100",
        "design_users": 100,
        "ssid": "InternalNet",
        "access_points": 2,
        "target_clients_per_ap": 50,
        "switch": "managed PoE+ 8-16 port, VLAN capable",
        "router": "2.5GbE-capable firewall/router",
        "backbone": "Cat6; 1GbE minimum, 2.5GbE preferred to APs/core",
        "internet_target": "1 Gbps starting service, measured and scaled to demand",
        "edge_role": "ung-edge-001 remains edge/control node; dedicated APs carry Wi-Fi clients",
        "vlans": VLANS,
        "scaling_rule": "add AP capacity and PoE switching without changing addressing/control architecture",
    }
