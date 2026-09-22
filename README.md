# Zabbix LXD / LXC Container Monitoring & Auto-Discovery

Production-grade automated Low-Level Discovery (LLD) and performance monitoring solution for LXD / LXC containers using Zabbix Agent 2 (or Zabbix Agent 1).

---

## Overview

Default Zabbix Linux monitoring templates (`Linux by Zabbix agent`) only track the host operating system and physical interfaces. They do not discover or inspect LXD / LXC container lifecycles, memory consumption, or per-container network statistics.

This solution provides:
- **Zero External Dependencies**: Uses a self-contained Python collector interacting directly with the local LXD Unix Domain Socket REST API.
- **Snap & Native Package Compatibility**: Automatically resolves socket paths for Snap deployments (`/var/snap/lxd/common/lxd/unix.socket`) and native Debian/Ubuntu packages (`/var/lib/lxd/unix.socket`).
- **Automated Lifecycle Discovery**: Instantly discovers new containers and purges deleted containers within 60 seconds.
- **Granular Metrics**: Real-time tracking of container state, IPv4 addresses, memory usage, memory peak, and network traffic (inbound/outbound bytes per second).
- **Autonomous Peak Memory Tracking**: Full compatibility with cgroup v2 on Linux kernels prior to 5.19 (e.g. Ubuntu 22.04 LTS Kernel 5.15) where `memory.peak` is not natively exposed by the kernel.
- **Comprehensive Alerting**: Built-in trigger prototypes for container downtime, missing IPv4 assignment, and telemetry loss.

---

## Architecture

```
+-------------------------------------------------------------------------+
|                              ZABBIX SERVER                              |
|   - Template: Template App LXD LXC Containers by Zabbix agent 2         |
|   - Discovery Rule: lxd.discovery                                       |
+------------------------------------+------------------------------------+
                                     |
                         Zabbix Poller (Port 10050)
                                     |
                                     v
+-------------------------------------------------------------------------+
|                                LXD HOST                                 |
|                                                                         |
|  [ Zabbix Agent 2 ]                                                     |
|         |                                                               |
|         +---> UserParameters (/etc/zabbix/zabbix_agent2.d/lxd.conf)     |
|                     |                                                   |
|                     v                                                   |
|         [ /etc/zabbix/scripts/lxd_monitor.py ]                          |
|                     |                                                   |
|                     v  (Unix Domain Socket)                             |
|         [ /var/snap/lxd/common/lxd/unix.socket ]                        |
|                     |                                                   |
|                     +---> LXD REST API (/1.0/instances)                 |
|                                                                         |
|  [ LXC Containers ]                                                     |
|    - container-01 (Running | 10.0.3.101 | Memory | Network I/O)         |
|    - container-02 (Running | 10.0.3.102 | Memory | Network I/O)         |
|    - container-03 (Running | 10.0.3.103 | Memory | Network I/O)         |
+-------------------------------------------------------------------------+
```

---

## Monitored Metrics & Items

| Metric Key | Description | Type | Update Interval |
| :--- | :--- | :--- | :--- |
| `lxd.discovery` | LLD rule discovering all LXD containers | JSON Array | 1m |
| `lxd.container.status[{#LXC.NAME}]` | Operational state (`Running`, `Stopped`, `Frozen`) | Character | 1m |
| `lxd.container.ipv4[{#LXC.NAME},eth0]` | Primary IPv4 address assigned to container | Character | 5m |
| `lxd.container.memory.usage[{#LXC.NAME}]` | Current memory consumption (Bytes) | Numeric (unsigned) | 1m |
| `lxd.container.memory.peak[{#LXC.NAME}]` | Peak memory recorded for container (Bytes) | Numeric (unsigned) | 5m |
| `lxd.container.net.rx[{#LXC.NAME},eth0]` | Incoming network bandwidth (Bytes/sec, Rate) | Numeric (unsigned) | 1m |
| `lxd.container.net.tx[{#LXC.NAME},eth0]` | Outgoing network bandwidth (Bytes/sec, Rate) | Numeric (unsigned) | 1m |

### Included Trigger Prototypes

1. **Container Not Running** (`High`):
   - Trigger Name: `LXC: Container [{#LXC.NAME}] is not running (state: {ITEM.VALUE})`
   - Expression: `last(/Template App LXD LXC Containers by Zabbix agent 2/lxd.container.status[{#LXC.NAME}])<>"Running"`
   - Automatically resolves when container returns to `Running` state.

2. **Container Missing IPv4 Address** (`Warning`):
   - Trigger Name: `LXC: Container [{#LXC.NAME}] has no IPv4 address on eth0`
   - Expression: `last(/Template App LXD LXC Containers by Zabbix agent 2/lxd.container.status[{#LXC.NAME}])="Running" and last(/Template App LXD LXC Containers by Zabbix agent 2/lxd.container.ipv4[{#LXC.NAME},eth0])="N/A"`
   - Alerts only when the container is in `Running` state but has no valid IPv4 assigned.

3. **Telemetry Lost** (`Warning`):
   - Trigger Name: `LXC: Container [{#LXC.NAME}] data is not received for 10m`
   - Expression: `nodata(/Template App LXD LXC Containers by Zabbix agent 2/lxd.container.status[{#LXC.NAME}],10m)=1`
   - Alerts if the host agent stops reporting data for the container for over 10 minutes.

---

## Operational Guide: Managing Manually Stopped Containers

When a container is intentionally decommissioned or stopped for maintenance, avoid disabling template triggers globally. Use one of the following standard workflows:

### Method A: Problem Suppression (Recommended - Fully Automated on Restart)
1. In the Zabbix Web UI, navigate to **Monitoring > Problems**.
2. Click on the problem event for the stopped container and select **Update**.
3. Check **Suppress problem** and select **Indefinitely** (or a maintenance window duration).
4. Enter an audit comment (e.g. `Decommissioned container` or `Maintenance`).
5. **Automatic Behavior**:
   - The alert is silenced and hidden from operational dashboards.
   - When the container is restarted (`lxc start`), its state becomes `Running`.
   - Zabbix automatically closes the problem and clears the suppression. Future unexpected crashes will alert normally.

### Method B: Disable Specific Trigger on Host
1. Navigate to **Configuration > Hosts > [Target Host] > Triggers**.
2. Filter by the container name.
3. Click the green **Enabled** status badge to toggle it to red **Disabled**.

---

## Installation & Deployment Guide

### Step 1: Grant Permissions to Zabbix User

The LXD Unix domain socket is protected and owned by the `lxd` system group (`0660`). The `zabbix` system user must be added to the `lxd` group to interact with the socket:

```bash
sudo usermod -aG lxd zabbix
```

### Step 2: Deploy the Collector Script

Create the directory and install the Python collector:

```bash
sudo mkdir -p /etc/zabbix/scripts
sudo curl -sSL https://raw.githubusercontent.com/lxl519/zabbix-lxd-lxc-discovery/main/scripts/lxd_monitor.py -o /etc/zabbix/scripts/lxd_monitor.py
sudo chmod 755 /etc/zabbix/scripts/lxd_monitor.py
```

Verify that the `zabbix` user can query the LXD socket:

```bash
sudo -u zabbix /etc/zabbix/scripts/lxd_monitor.py discover
```

Expected output:
```json
[{"{#LXC.NAME}": "container-01", "{#LXC.STATUS}": "Running", "{#LXC.IPV4}": "10.0.3.101"}]
```

### Step 3: Configure Zabbix Agent 2 UserParameters

Download the configuration file into the Zabbix Agent 2 configuration directory:

```bash
sudo curl -sSL https://raw.githubusercontent.com/lxl519/zabbix-lxd-lxc-discovery/main/zabbix_agent2.d/lxd.conf -o /etc/zabbix/zabbix_agent2.d/lxd.conf
```

*(For Zabbix Agent 1, place the file in `/etc/zabbix/zabbix_agentd.d/lxd.conf`)*.

Ensure your Zabbix Server or Proxy IP (including NAT egress public IP if monitoring across WAN) is allowed in `/etc/zabbix/zabbix_agent2.conf`:

```ini
Server=127.0.0.1,192.168.1.100,YOUR_ZABBIX_SERVER_PUBLIC_IP
```

Restart the Zabbix Agent service:

```bash
# For Zabbix Agent 2
sudo systemctl restart zabbix-agent2

# For Zabbix Agent 1
sudo systemctl restart zabbix-agent
```

### Step 4: Import Zabbix Template

1. Download the template from `templates/template_app_lxd_lxc_containers.yaml`.
2. In the Zabbix Web UI:
   - Navigate to **Data collection > Templates** (or **Configuration > Templates**).
   - Click **Import** in the top right corner.
   - Select `template_app_lxd_lxc_containers.yaml` and click **Import**.
3. Link the template:
   - Navigate to **Data collection > Hosts** (or **Configuration > Hosts**).
   - Select your LXD Host node.
   - Under the **Templates** tab, add **`Template App LXD LXC Containers by Zabbix agent 2`**.
   - Click **Update**.

---

## Verification & Testing

From the Zabbix Server or Proxy, run `zabbix_get` against the LXD host IP:

```bash
# Test Discovery
zabbix_get -s 10.0.3.1 -k "lxd.discovery"

# Test Container State
zabbix_get -s 10.0.3.1 -k "lxd.container.status[container-01]"

# Test Memory Usage
zabbix_get -s 10.0.3.1 -k "lxd.container.memory.usage[container-01]"

# Test Memory Peak
zabbix_get -s 10.0.3.1 -k "lxd.container.memory.peak[container-01]"

# Test Container IPv4
zabbix_get -s 10.0.3.1 -k "lxd.container.ipv4[container-01,eth0]"
```

---

## Security & Design Notes

- **No Root Required**: The collector runs strictly with unprivileged `zabbix` user permissions using read-only access to `/1.0/instances`.
- **No Snap Confinement Conflicts**: Standard `/snap/bin/lxc` commands enforce strict home directory AppArmor confinements when invoked under service accounts. Direct Unix socket communication completely avoids snap confinement overhead.
- **Low Overhead**: Unix Domain Socket communication eliminates TCP connection overhead and minimizes CPU utilization during polling cycles.
- **cgroup v2 Compatibility**: Implements self-healing PID-bound high-water mark memory peak tracking when running on Linux kernels < 5.19 without native `memory.peak` support.

---

## Compatibility

- **Operating Systems**: Ubuntu 20.04 LTS, Ubuntu 22.04 LTS, Ubuntu 24.04 LTS, Debian 11, Debian 12.
- **LXD / Incus Versions**: LXD 4.x, LXD 5.x, Incus 0.x, Incus 6.x.
- **Zabbix Versions**: Zabbix 6.0 LTS, Zabbix 6.4, Zabbix 7.0 LTS, Zabbix 7.2.

---

## License

This project is open-source software licensed under the [MIT License](LICENSE).
