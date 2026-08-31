#!/usr/bin/env python3
# ==============================================================================
# Script: lxd_monitor.py
# Purpose: LXD / LXC Container Auto-Discovery (LLD) & Metrics Collector for Zabbix
# Description: Interacts directly with the local LXD Unix Domain Socket REST API
#              without external dependencies or snap confinement issues.
# ==============================================================================

import sys
import json
import http.client
import socket
import os

# Standard LXD socket paths (snap package and native deb/apt package)
DEFAULT_SOCKET_PATHS = [
    "/var/snap/lxd/common/lxd/unix.socket",
    "/var/lib/lxd/unix.socket",
    "/run/lxd.socket"
]

def get_socket_path():
    for path in DEFAULT_SOCKET_PATHS:
        if os.path.exists(path):
            return path
    return DEFAULT_SOCKET_PATHS[0]

SOCKET_PATH = get_socket_path()

class UnixHTTPConnection(http.client.HTTPConnection):
    def __init__(self, socket_path):
        super().__init__("localhost")
        self.socket_path = socket_path

    def connect(self):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.connect(self.socket_path)

def query_lxd(endpoint):
    try:
        conn = UnixHTTPConnection(SOCKET_PATH)
        conn.request("GET", endpoint)
        resp = conn.getresponse()
        data = resp.read().decode("utf-8")
        conn.close()
        res = json.loads(data)
        return res.get("metadata")
    except Exception:
        return None

def discover():
    instances = query_lxd("/1.0/instances")
    lld = []
    if isinstance(instances, list):
        for inst_path in instances:
            name = inst_path.strip().split("/")[-1]
            if not name:
                continue
            state = query_lxd(f"/1.0/instances/{name}/state")
            status = state.get("status", "Unknown") if isinstance(state, dict) else "Unknown"
            ipv4 = "N/A"
            if isinstance(state, dict):
                network = state.get("network", {})
                if isinstance(network, dict):
                    for ifname, ifdata in network.items():
                        for addr in ifdata.get("addresses", []):
                            if addr.get("family") == "inet" and addr.get("scope") == "global":
                                ipv4 = addr.get("address")
                                break
                        if ipv4 != "N/A":
                            break
            lld.append({
                "{#LXC.NAME}": name,
                "{#LXC.STATUS}": status,
                "{#LXC.IPV4}": ipv4
            })
    print(json.dumps(lld))

def get_metric(name, metric, subkey=None):
    state = query_lxd(f"/1.0/instances/{name}/state")
    if not isinstance(state, dict) or not state:
        if metric in ["status", "ipv4"]:
            print("Unknown")
        else:
            print("0")
        return

    if metric == "status":
        print(state.get("status", "Unknown"))
    elif metric == "status_code":
        print(state.get("status_code", 0))
    elif metric == "memory_usage":
        print(state.get("memory", {}).get("usage", 0))
    elif metric == "memory_peak":
        print(state.get("memory", {}).get("usage_peak", 0))
    elif metric == "memory_swap":
        print(state.get("memory", {}).get("swap_usage", 0))
    elif metric == "cpu_usage":
        print(state.get("cpu", {}).get("usage", 0))
    elif metric == "disk_usage":
        disk = state.get("disk", {})
        root_disk = disk.get("root", {}) if isinstance(disk, dict) else {}
        print(root_disk.get("usage", 0) if isinstance(root_disk, dict) else 0)
    elif metric == "net_rx":
        iface = subkey or "eth0"
        print(state.get("network", {}).get(iface, {}).get("counters", {}).get("bytes_received", 0))
    elif metric == "net_tx":
        iface = subkey or "eth0"
        print(state.get("network", {}).get(iface, {}).get("counters", {}).get("bytes_sent", 0))
    elif metric == "ipv4":
        iface = subkey or "eth0"
        addresses = state.get("network", {}).get(iface, {}).get("addresses", [])
        for addr in addresses:
            if addr.get("family") == "inet" and addr.get("scope") == "global":
                print(addr.get("address"))
                return
        print("N/A")
    else:
        print("0")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: lxd_monitor.py discover | get <name> <metric> [subkey]")
        sys.exit(1)
    
    cmd = sys.argv[1]
    if cmd == "discover":
        discover()
    elif cmd == "get" and len(sys.argv) >= 4:
        name = sys.argv[2]
        metric = sys.argv[3]
        subkey = sys.argv[4] if len(sys.argv) > 4 else None
        get_metric(name, metric, subkey)
    else:
        print("Invalid arguments")
