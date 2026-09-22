#!/usr/bin/env python3
import sys
import json
import http.client
import socket
import os

SOCKET_PATH = "/var/snap/lxd/common/lxd/unix.socket"

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
        return res.get("metadata", {})
    except Exception as e:
        return {}

def discover():
    instances = query_lxd("/1.0/instances")
    lld = []
    if isinstance(instances, list):
        for inst_path in instances:
            name = inst_path.split("/")[-1]
            state = query_lxd(f"/1.0/instances/{name}/state")
            status = state.get("status", "Unknown") if isinstance(state, dict) else "Unknown"
            ipv4 = "N/A"
            network = state.get("network", {}) if isinstance(state, dict) else {}
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

def get_or_update_peak(name, state):
    lxd_peak = state.get("memory", {}).get("usage_peak", 0)
    if lxd_peak and lxd_peak > 0:
        return lxd_peak

    usage = state.get("memory", {}).get("usage", 0)
    pid = state.get("pid", 0)
    if not pid or state.get("status") != "Running":
        return 0

    cache_file = f"/tmp/lxd_peak_{name}.json"
    peak = usage
    try:
        if os.path.exists(cache_file):
            with open(cache_file, "r") as f:
                data = json.load(f)
                if data.get("pid") == pid:
                    cached_peak = data.get("peak", 0)
                    if cached_peak > peak:
                        peak = cached_peak
        with open(cache_file, "w") as f:
            json.dump({"pid": pid, "peak": peak}, f)
        try:
            os.chmod(cache_file, 0o666)
        except Exception:
            pass
    except Exception:
        pass
    return peak

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
        usage = state.get("memory", {}).get("usage", 0)
        get_or_update_peak(name, state)
        print(usage)
    elif metric == "memory_peak":
        print(get_or_update_peak(name, state))
    elif metric == "memory_swap":
        print(state.get("memory", {}).get("swap_usage", 0))
    elif metric == "cpu_usage":
        ns = state.get("cpu", {}).get("usage", 0)
        print(ns)
    elif metric == "disk_usage":
        print(state.get("disk", {}).get("root", {}).get("usage", 0))
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
