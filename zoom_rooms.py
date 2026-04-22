#!/usr/bin/env python3
"""
zoom_rooms.py — Validate Zoom Room status and hardware inventory.

Usage:
    python zoom_rooms.py                         # All rooms
    python zoom_rooms.py --room-name "conf a"    # Filter by name (case-insensitive)
    python zoom_rooms.py --room-id <roomId>      # Specific room by ID

Credentials (.env file):
    ZOOM_ACCOUNT_ID
    ZOOM_CLIENT_ID
    ZOOM_CLIENT_SECRET

Required Zoom app scopes:
    room:read:list_rooms:admin
    room:read:room:admin
    room:read:device:admin
    dashboard_zoomrooms:read:admin
"""

import argparse
import os
import sys

import requests
from dotenv import load_dotenv


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

def get_access_token(account_id: str, client_id: str, client_secret: str) -> str:
    url = f"https://zoom.us/oauth/token?grant_type=account_credentials&account_id={account_id}"
    try:
        resp = requests.post(url, auth=(client_id, client_secret), timeout=10)
    except requests.exceptions.ConnectionError:
        sys.exit("ERROR: Could not connect to Zoom OAuth endpoint. Check your network.")

    if resp.status_code == 401:
        sys.exit("ERROR: Authentication failed — check ZOOM_CLIENT_ID, ZOOM_CLIENT_SECRET, and app scopes.")
    if not resp.ok:
        sys.exit(f"ERROR: Token request failed ({resp.status_code}): {resp.text}")

    return resp.json()["access_token"]


# ---------------------------------------------------------------------------
# API helpers
# ---------------------------------------------------------------------------

def _checked_get(session: requests.Session, url: str, params: dict = None, silent_404: bool = False) -> dict | None:
    """GET with centralised error handling. Returns None on 404, exits on fatal errors."""
    try:
        resp = session.get(url, params=params, timeout=10)
    except requests.exceptions.ConnectionError:
        sys.exit("ERROR: Lost connection to Zoom API.")

    if resp.status_code == 401:
        sys.exit("ERROR: Access denied — token expired or missing required scopes.")
    if resp.status_code == 404:
        if not silent_404:
            print(f"  WARNING: Resource not found: {url}")
        return None
    if resp.status_code == 429:
        retry_after = resp.headers.get("Retry-After", "unknown")
        print(f"  WARNING: Rate limited. Retry after {retry_after}s.")
        return None
    if not resp.ok:
        print(f"  WARNING: Unexpected response ({resp.status_code}) from {url}: {resp.text[:200]}")
        return None

    return resp.json()


# ---------------------------------------------------------------------------
# Zoom Rooms API calls
# ---------------------------------------------------------------------------

def list_all_rooms(session: requests.Session) -> list[dict]:
    rooms = []
    params = {"page_size": 100}
    while True:
        data = _checked_get(session, "https://api.zoom.us/v2/rooms", params=params)
        if not data:
            break
        rooms.extend(data.get("rooms", []))
        next_token = data.get("next_page_token")
        if not next_token:
            break
        params = {"page_size": 100, "next_page_token": next_token}
    return rooms


def get_room_detail(session: requests.Session, room_id: str) -> dict | None:
    return _checked_get(session, f"https://api.zoom.us/v2/rooms/{room_id}")


def get_room_devices(session: requests.Session, room_id: str) -> list[dict]:
    data = _checked_get(session, f"https://api.zoom.us/v2/rooms/{room_id}/devices")
    if not data:
        return []
    return data.get("devices", [])


def build_metrics_index(session: requests.Session) -> dict[str, dict]:
    """
    Fetch all metrics rooms and return a dict keyed by room_name.
    The metrics API uses different IDs than the rooms API, so we match by name.
    """
    index = {}
    params = {"page_size": 300}
    while True:
        data = _checked_get(session, "https://api.zoom.us/v2/metrics/zoomrooms", params=params, silent_404=True)
        if not data:
            break
        for room in data.get("zoom_rooms", []):
            name = room.get("room_name", "")
            if name:
                index[name] = room
        next_token = data.get("next_page_token")
        if not next_token:
            break
        params = {"page_size": 300, "next_page_token": next_token}
    return index


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

def _row(label: str, value: str, width: int = 20) -> str:
    return f"  {label:<{width}}: {value}"


def print_room_report(room: dict, devices: list[dict], metrics: dict | None) -> None:
    name   = room.get("name", "Unknown")
    status = room.get("status", "Unknown")
    room_id = room.get("id") or room.get("room_id", "Unknown")

    # Pull metrics fields
    health   = (metrics or {}).get("health", "")
    issues   = [i for i in (metrics or {}).get("issues", []) if i]
    camera   = (metrics or {}).get("camera", "")
    mic      = (metrics or {}).get("microphone", "")
    speaker  = (metrics or {}).get("speaker", "")
    cal_name = (metrics or {}).get("calendar_name", "")
    acct_type = (metrics or {}).get("account_type", "")
    last_start = (metrics or {}).get("last_start_time", "")
    device_ips = (metrics or {}).get("device_ip", "")

    # Past meeting count (metrics includes last 2 days by default)
    past_meetings = (metrics or {}).get("past_meetings", {})
    meeting_count = past_meetings.get("total_records", "")

    print()
    print("=" * 80)
    print(f"  ROOM: {name}")
    print("=" * 80)

    # Room-level info
    print(_row("Room ID", room_id))
    print(_row("Status", status))
    if health:
        print(_row("Health", health))
    if issues:
        print(_row("Issues", ", ".join(issues)))
    if cal_name:
        print(_row("Calendar", cal_name))
    if acct_type:
        print(_row("Account type", acct_type))
    if last_start:
        print(_row("Last meeting start", last_start))
    if meeting_count != "":
        print(_row("Meetings (48h)", str(meeting_count)))

    # Peripherals
    if any([camera, mic, speaker]):
        print()
        print("  Peripherals:")
        if camera:
            print(_row("  Camera", camera))
        if mic:
            print(_row("  Microphone", mic))
        if speaker:
            print(_row("  Speaker", speaker))

    # Device IPs from metrics (more detailed breakdown than per-device)
    if device_ips:
        print()
        print("  Device IPs (from metrics):")
        for entry in device_ips.split(";"):
            entry = entry.strip()
            if entry:
                print(f"    {entry}")

    # Per-device table
    if not devices:
        print("\n  No devices found.")
        print("=" * 80)
        return

    print()
    print(f"  Devices ({len(devices)}):")

    col_type     = 20
    col_status   = 9
    col_hostname = 24
    col_model    = 16
    col_ip       = 17
    col_ver      = 16
    col_os       = 20

    header = (
        f"  {'#':>2}  "
        f"{'Type':<{col_type}}  "
        f"{'Status':<{col_status}}  "
        f"{'Hostname':<{col_hostname}}  "
        f"{'Model':<{col_model}}  "
        f"{'IP Address':<{col_ip}}  "
        f"{'App Version':<{col_ver}}  "
        f"{'OS':<{col_os}}"
    )
    separator = "  " + "-" * (len(header) - 2)

    print(separator)
    print(header)
    print(separator)

    for i, dev in enumerate(devices, start=1):
        d_type     = dev.get("device_type", "")
        d_status   = dev.get("status", "")
        d_hostname = dev.get("device_hostname", "")
        d_model    = dev.get("device_model", "")
        d_ip       = dev.get("ip_address", "")
        d_ver      = dev.get("app_version", "")
        d_os       = dev.get("device_system", "")
        print(
            f"  {i:>2}  "
            f"{d_type:<{col_type}}  "
            f"{d_status:<{col_status}}  "
            f"{d_hostname:<{col_hostname}}  "
            f"{d_model:<{col_model}}  "
            f"{d_ip:<{col_ip}}  "
            f"{d_ver:<{col_ver}}  "
            f"{d_os:<{col_os}}"
        )

    print(separator)
    print("=" * 80)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    load_dotenv()

    # Credentials
    account_id    = os.environ.get("ZOOM_ACCOUNT_ID")
    client_id     = os.environ.get("ZOOM_CLIENT_ID")
    client_secret = os.environ.get("ZOOM_CLIENT_SECRET")

    missing = [k for k, v in {
        "ZOOM_ACCOUNT_ID": account_id,
        "ZOOM_CLIENT_ID": client_id,
        "ZOOM_CLIENT_SECRET": client_secret,
    }.items() if not v]
    if missing:
        sys.exit(f"ERROR: Missing required environment variable(s): {', '.join(missing)}")

    # CLI args
    parser = argparse.ArgumentParser(description="Validate Zoom Room status and hardware.")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--room-name", metavar="NAME", help="Filter rooms by partial name (case-insensitive)")
    group.add_argument("--room-id",   metavar="ID",   help="Look up a specific room by exact ID")
    args = parser.parse_args()

    # Auth
    print("Authenticating with Zoom...")
    token = get_access_token(account_id, client_id, client_secret)

    session = requests.Session()
    session.headers.update({"Authorization": f"Bearer {token}"})

    # Determine rooms to process
    if args.room_id:
        detail = get_room_detail(session, args.room_id)
        rooms_to_process = [detail] if detail else []
    else:
        print("Fetching room list...")
        all_rooms = list_all_rooms(session)
        if args.room_name:
            filter_str = args.room_name.lower()
            rooms_to_process = [r for r in all_rooms if filter_str in r.get("name", "").lower()]
            if not rooms_to_process:
                sys.exit(f"No rooms matched '{args.room_name}'.")
        else:
            rooms_to_process = all_rooms

    if not rooms_to_process:
        sys.exit("No rooms found.")

    print(f"Checking {len(rooms_to_process)} room(s)...")
    print("Fetching metrics index...")
    metrics_index = build_metrics_index(session)
    print()

    online_count  = 0
    offline_count = 0

    for room in rooms_to_process:
        room_id = room.get("id") or room.get("room_id")
        if not room_id:
            continue

        # Fetch full detail if we only have a list stub
        if "status" not in room or len(room) < 4:
            detail = get_room_detail(session, room_id)
            if not detail:
                continue
            room = detail

        room_name = room.get("name", "")
        devices = get_room_devices(session, room_id)
        metrics = metrics_index.get(room_name)
        print_room_report(room, devices, metrics)

        status = (room.get("status") or "").lower()
        if status in ("available", "online", "in_meeting"):
            online_count += 1
        else:
            offline_count += 1

    total = online_count + offline_count
    print(f"\nChecked {total} room(s): {online_count} online/available, {offline_count} offline/unknown.")


if __name__ == "__main__":
    main()
