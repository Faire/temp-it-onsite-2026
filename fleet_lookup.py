from __future__ import annotations

import os
import sys
import requests
from dotenv import load_dotenv

load_dotenv()

FLEET_API_URL = os.getenv("FLEET_API_URL", "").rstrip("/").removesuffix("/api/v1/fleet")
FLEET_API_TOKEN = os.getenv("FLEET_API_TOKEN", "")


def get_headers():
    return {"Authorization": f"Bearer {FLEET_API_TOKEN}"}


def find_host_by_serial(serial: str) -> dict | None:
    response = requests.get(
        f"{FLEET_API_URL}/api/v1/fleet/hosts",
        headers=get_headers(),
        params={"query": serial},
    )
    response.raise_for_status()
    hosts = response.json().get("hosts", [])
    for host in hosts:
        if host.get("hardware_serial", "").upper() == serial.upper():
            return host
    return hosts[0] if hosts else None


def get_host_details(host_id: int) -> dict:
    response = requests.get(
        f"{FLEET_API_URL}/api/v1/fleet/hosts/{host_id}",
        headers=get_headers(),
    )
    response.raise_for_status()
    return response.json().get("host", {})


def fmt(value, default="N/A"):
    if value is None or value == "":
        return default
    return str(value)


def fmt_date(value):
    if not value:
        return "N/A"
    return str(value)[:10]


def fmt_datetime(value):
    if not value:
        return "N/A"
    return str(value)[:16].replace("T", " ")


def fmt_bytes(b):
    if not b:
        return "N/A"
    return f"{b / (1024 ** 3):.1f} GB"


def fmt_ns(ns):
    if not ns:
        return "N/A"
    hours = ns // 3_600_000_000_000
    return f"{hours // 24}d {hours % 24}h"


def section(title: str):
    print(f"\n{'─' * 55}")
    print(f"  {title}")
    print(f"{'─' * 55}")


COL1, COL2 = 26, 40

def table_header():
    print(f"┌{'─' * (COL1 + 2)}┬{'─' * (COL2 + 2)}┐")
    print(f"│ {'Field':<{COL1}} │ {'Value':<{COL2}} │")
    print(f"├{'─' * (COL1 + 2)}┼{'─' * (COL2 + 2)}┤")

def table_footer():
    print(f"└{'─' * (COL1 + 2)}┴{'─' * (COL2 + 2)}┘")

def row(label: str, value, last=False):
    v = fmt(value)
    print(f"│ {label:<{COL1}} │ {v:<{COL2}} │")
    if not last:
        print(f"├{'─' * (COL1 + 2)}┼{'─' * (COL2 + 2)}┤")


def print_host_info(host: dict):
    mdm = host.get("mdm") or {}
    battery = (host.get("batteries") or [{}])[0]

    total = host.get("gigs_total_disk_space", "N/A")
    avail = host.get("gigs_disk_space_available", "N/A")
    disk_str = f"{avail} GB free / {total} GB total"

    os_build = f"{fmt(host.get('os_version'))} ({fmt(host.get('build'))})"

    battery_str = fmt(battery.get("health"))
    if battery.get("cycle_count") is not None:
        battery_str += f", {battery.get('cycle_count')} cycles"

    vuln_software = [
        s for s in (host.get("software") or [])
        if s.get("vulnerabilities")
    ]

    cpu = host.get("cpu_brand", "")
    chip = cpu.replace("Apple ", "") if cpu else ""
    model_str = f"{fmt(host.get('hardware_model'))} ({chip})" if chip else fmt(host.get("hardware_model"))

    print()
    table_header()
    row("Model", model_str)
    row("Memory", fmt_bytes(host.get("memory")))
    row("Disk", disk_str)
    row("OS Build", os_build)
    row("Uptime", fmt_ns(host.get("uptime")))
    row("MDM Status", mdm.get("enrollment_status"))
    row("Battery Health", battery_str)
    row("Added to Fleet", fmt_date(host.get("created_at")))
    row("Last MDM Check-in", fmt_datetime(host.get("last_mdm_checked_in_at")))
    row("Software Needs Update", len(vuln_software), last=True)
    table_footer()

    if vuln_software:
        print("\n  Software with vulnerabilities:")
        for s in vuln_software:
            cve_count = len(s.get("vulnerabilities") or [])
            print(f"    - {s['name']} {s['version']} ({cve_count} CVE{'s' if cve_count != 1 else ''})")

    print()


def main():
    if len(sys.argv) < 2:
        print("Usage: python3 fleet_lookup.py <SERIAL_NUMBER>")
        sys.exit(1)

    if not FLEET_API_URL or not FLEET_API_TOKEN:
        print("Error: FLEET_API_URL and FLEET_API_TOKEN must be set in your .env file.")
        sys.exit(1)

    serial = sys.argv[1].strip()
    print(f"Looking up serial: {serial}")

    host_summary = find_host_by_serial(serial)
    if not host_summary:
        print(f"No device found with serial number: {serial}")
        sys.exit(1)

    host = get_host_details(host_summary["id"])
    print_host_info(host)


if __name__ == "__main__":
    main()
