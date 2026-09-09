# UNG-INTERNALNET

Production internal Wi-Fi/AP service for UNG edge nodes.

## Purpose
UNG-INTERNALNET turns a supported Linux Wi-Fi interface into the private `InternalNet` access network used by authorized UNG devices. It is intentionally separate from UNG-EDGE.

## Safety model
Live activation is explicit. The service does not alter networking merely by starting the API. `pi_installer.py --apply` performs host preparation; `/api/network/apply` requires `UNG_INTERNALNET_LIVE=1` and an admin token.

## Components
- FastAPI management/health API
- hostapd configuration rendering
- dnsmasq DHCP/DNS configuration rendering
- nftables NAT/firewall configuration rendering
- live installer/apply path
- configuration backup and rollback
- systemd service templates

## Default network
- SSID: `InternalNet`
- AP interface: `wlan0`
- subnet: `10.77.0.0/24`
- gateway: `10.77.0.1`
- DHCP: `10.77.0.50-10.77.0.200`

Change defaults with environment variables before production use. Never commit Wi-Fi passwords or admin tokens.
