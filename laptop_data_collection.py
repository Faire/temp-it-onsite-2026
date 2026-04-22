"""
Laptop Data Collection Layer
Uses the Fleet API to retrieve software versions and device info for a given serial number.

Setup:
    export FLEET_API_KEY="your_key_from_1password"
    export FLEET_BASE_URL="https://your-fleet-instance.example.com"

Usage:
    python3 laptop_data_collection.py <serial_number>
"""

import os
import sys
import re as _re
import requests
from datetime import datetime, timezone


_raw_url = os.environ.get("FLEET_BASE_URL", "")
FLEET_BASE_URL = _re.sub(r"/api/v1/fleet.*$", "", _raw_url).rstrip("/")
FLEET_API_KEY = os.environ.get("FLEET_API_KEY", "")


def get_headers():
    if not FLEET_API_KEY:
        raise EnvironmentError("FLEET_API_KEY environment variable is not set.")
    if not FLEET_BASE_URL:
        raise EnvironmentError("FLEET_BASE_URL environment variable is not set.")
    return {"Authorization": f"Bearer {FLEET_API_KEY}"}


def get_host_by_serial(serial_number):
    url = f"{FLEET_BASE_URL}/api/v1/fleet/hosts/identifier/{serial_number}"
    response = requests.get(url, headers=get_headers(), timeout=10)
    response.raise_for_status()
    return response.json().get("host", {})


def fmt_date(iso):
    if not iso:
        return "N/A"
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        return dt.strftime("%Y-%m-%d")
    except Exception:
        return iso


def fmt_datetime(iso):
    if not iso:
        return "N/A"
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        return dt.strftime("%Y-%m-%d %H:%M")
    except Exception:
        return iso


def fmt_uptime(uptime_ns):
    if not uptime_ns:
        return "N/A"
    total_minutes = int(uptime_ns / 6e10)
    days = total_minutes // 1440
    hours = (total_minutes % 1440) // 60
    return f"{days}d {hours}h"


def fmt_model(model):
    friendly = {
        "Mac16,7": "M4 Pro", "Mac16,6": "M4 Pro", "Mac16,5": "M4 Max",
        "Mac15,6": "M3 Pro", "Mac15,7": "M3 Pro", "Mac15,8": "M3 Max",
        "Mac14,5": "M2 Pro", "Mac14,6": "M2 Max", "Mac14,3": "M2",
        "MacBookPro18,1": "M1 Pro", "MacBookPro18,2": "M1 Max",
        "MacBookPro17,1": "M1",
    }
    label = friendly.get(model, "")
    return f"{model} ({label})" if label else model


def extract_info(host):
    memory_bytes = host.get("memory")
    memory_gb = round(memory_bytes / (1024 ** 3), 1) if memory_bytes else None

    batteries = host.get("batteries") or []
    battery = batteries[0] if batteries else {}
    battery_str = battery.get("health", "N/A")
    if battery.get("cycle_count") is not None:
        battery_str += f", {battery['cycle_count']} cycles"

    mdm = host.get("mdm") or {}

    update_keywords = {"update", "patch", "current", "upgrade", "version"}
    policies = host.get("policies") or []
    failing_updates = sum(
        1 for p in policies
        if p.get("response") == "fail"
        and any(kw in p.get("name", "").lower() for kw in update_keywords)
    )

    software = host.get("software") or []
    vulnerable = [
        f"{s['name']} {s.get('version', '')} ({len(s['vulnerabilities'])} CVE{'s' if len(s['vulnerabilities']) != 1 else ''})"
        for s in software
        if s.get("vulnerabilities")
    ]

    os_str = host.get("os_version", "")
    build = host.get("build", "")
    os_build = f"{os_str} ({build})" if build else os_str

    return {
        "rows": [
            ("Model",               fmt_model(host.get("hardware_model", ""))),
            ("Memory",              f"{memory_gb} GB"),
            ("Disk",                f"{host.get('gigs_disk_space_available')} GB free / {host.get('gigs_total_disk_space')} GB total"),
            ("OS Build",            os_build),
            ("Uptime",              fmt_uptime(host.get("uptime"))),
            ("MDM Status",          mdm.get("enrollment_status", "N/A")),
            ("Battery Health",      battery_str),
            ("Added to Fleet",      fmt_date(host.get("created_at"))),
            ("Last MDM Check-in",   fmt_datetime(host.get("last_mdm_checked_in_at"))),
            ("Software Needs Update", str(failing_updates) if failing_updates else "0"),
        ],
        "vulnerabilities": vulnerable,
    }


def print_table(serial, data):
    rows = data["rows"]
    col_w = max(len(r[0]) for r in rows) + 2
    val_w = max(len(str(r[1])) for r in rows) + 2
    border = f"+{'-' * (col_w + 2)}+{'-' * (val_w + 2)}+"

    print(f"\nLooking up serial: {serial}\n")
    print(border)
    print(f"| {'Field':<{col_w}} | {'Value':<{val_w}} |")
    print(border)
    for label, value in rows:
        print(f"| {label:<{col_w}} | {str(value):<{val_w}} |")
    print(border)

    if data["vulnerabilities"]:
        print(f"\nSoftware with vulnerabilities:")
        for v in data["vulnerabilities"]:
            print(f"  - {v}")


def collect(serial_number):
    host = get_host_by_serial(serial_number)
    if not host:
        print("No host found for that serial number.")
        return
    data = extract_info(host)
    print_table(serial_number, data)
    return data


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python3 laptop_data_collection.py <serial_number>")
        sys.exit(1)

    serial = sys.argv[1]

    try:
        collect(serial)
    except EnvironmentError as e:
        print(f"Configuration error: {e}")
        sys.exit(1)
    except requests.HTTPError as e:
        print(f"Fleet API error: {e.response.status_code} - {e.response.text}")
        sys.exit(1)
    except requests.ConnectionError:
        print("Could not connect to Fleet. Check FLEET_BASE_URL.")
        sys.exit(1)
