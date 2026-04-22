"""
jira_device_comment.py

Usage: python jira_device_comment.py <JIRA-TICKET>

Fetches the reporter's email from a Jira ticket, looks up their device(s)
via Teqtivity (get_device_info.py) and Fleet (fleet_lookup.py), extracts a
Zoom room name from the ticket description using Claude, queries Zoom room
status (zoom_rooms.py), then posts a formatted comment back to the ticket.

Required env vars (via .env):
    JIRA_BASE_URL, JIRA_EMAIL, JIRA_API_TOKEN
    TEQTIVITY_API_URL, TEQTIVITY_API_KEY
    FLEET_API_URL, FLEET_API_TOKEN
    ZOOM_ACCOUNT_ID, ZOOM_CLIENT_ID, ZOOM_CLIENT_SECRET
    ANTHROPIC_API_KEY
"""

import argparse
import os
import sys

import anthropic
import requests
from dotenv import load_dotenv

from get_device_info import get_devices_by_user, parse_tech_specs
from fleet_lookup import find_host_by_serial, get_host_details, fmt, fmt_date, fmt_datetime, fmt_bytes, fmt_ns
from zoom_rooms import get_access_token, list_all_rooms, get_room_detail, get_room_devices, build_metrics_index

load_dotenv()

JIRA_BASE_URL = os.getenv("JIRA_BASE_URL", "").rstrip("/")
JIRA_EMAIL = os.getenv("JIRA_EMAIL")
JIRA_API_TOKEN = os.getenv("JIRA_API_TOKEN")


def validate_env():
    required = {
        "JIRA_BASE_URL": JIRA_BASE_URL,
        "JIRA_EMAIL": JIRA_EMAIL,
        "JIRA_API_TOKEN": JIRA_API_TOKEN,
        "TEQTIVITY_API_URL": os.getenv("TEQTIVITY_API_URL"),
        "TEQTIVITY_API_KEY": os.getenv("TEQTIVITY_API_KEY"),
        "FLEET_API_URL": os.getenv("FLEET_API_URL"),
        "FLEET_API_TOKEN": os.getenv("FLEET_API_TOKEN"),
        "ZOOM_ACCOUNT_ID": os.getenv("ZOOM_ACCOUNT_ID"),
        "ZOOM_CLIENT_ID": os.getenv("ZOOM_CLIENT_ID"),
        "ZOOM_CLIENT_SECRET": os.getenv("ZOOM_CLIENT_SECRET"),
        "ANTHROPIC_API_KEY": os.getenv("ANTHROPIC_API_KEY"),
    }
    missing = [k for k, v in required.items() if not v]
    if missing:
        print(f"Error: missing environment variable(s): {', '.join(missing)}")
        print("Make sure your .env file is populated.")
        sys.exit(1)


# ---------------------------------------------------------------------------
# Jira helpers
# ---------------------------------------------------------------------------

def get_jira_issue(issue_key: str) -> dict:
    url = f"{JIRA_BASE_URL}/rest/api/3/issue/{issue_key}?fields=reporter,description"
    response = requests.get(url, auth=(JIRA_EMAIL, JIRA_API_TOKEN))
    response.raise_for_status()
    return response.json()


def extract_reporter_email(issue: dict, issue_key: str) -> str:
    reporter = issue.get("fields", {}).get("reporter", {})
    email = reporter.get("emailAddress")
    if not email:
        print(f"Error: no reporter email found on issue {issue_key}")
        sys.exit(1)
    return email


def adf_to_text(node: dict) -> str:
    """Recursively extract plain text from an Atlassian Document Format node."""
    if not node:
        return ""
    node_type = node.get("type", "")
    if node_type == "text":
        return node.get("text", "")
    text = " ".join(adf_to_text(child) for child in node.get("content", []))
    if node_type in ("paragraph", "heading", "listItem", "bulletList", "orderedList"):
        return text + "\n"
    return text


def get_description_text(issue: dict) -> str:
    description = issue.get("fields", {}).get("description")
    if not description:
        return ""
    return adf_to_text(description).strip()


# ---------------------------------------------------------------------------
# Zoom room extraction via Claude
# ---------------------------------------------------------------------------

def extract_zoom_room_name(description: str) -> str | None:
    """Use Claude to extract a Zoom room name from the ticket description."""
    if not description:
        return None

    client = anthropic.Anthropic()
    message = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=256,
        system=(
            "You extract Zoom room names from IT support ticket descriptions. "
            "Reply with ONLY the room name if one is present, or the single word NONE if no room name is found. "
            "Do not explain or add any other text."
        ),
        messages=[{"role": "user", "content": description}],
    )
    result = message.content[0].text.strip()
    return None if result.upper() == "NONE" else result


# ---------------------------------------------------------------------------
# Zoom room lookup
# ---------------------------------------------------------------------------

def get_zoom_room_info(room_name: str) -> dict | None:
    """Return a dict with room detail, devices, and metrics for the named room."""
    account_id = os.getenv("ZOOM_ACCOUNT_ID")
    client_id = os.getenv("ZOOM_CLIENT_ID")
    client_secret = os.getenv("ZOOM_CLIENT_SECRET")

    try:
        token = get_access_token(account_id, client_id, client_secret)
    except SystemExit:
        return None

    session = requests.Session()
    session.headers.update({"Authorization": f"Bearer {token}"})

    all_rooms = list_all_rooms(session)
    matched = next(
        (r for r in all_rooms if r.get("name", "").lower() == room_name.lower()),
        None,
    )
    # Fall back to partial match
    if not matched:
        matched = next(
            (r for r in all_rooms if room_name.lower() in r.get("name", "").lower()),
            None,
        )
    if not matched:
        return None

    room_id = matched.get("id") or matched.get("room_id")
    detail = get_room_detail(session, room_id) or matched
    devices = get_room_devices(session, room_id)
    metrics_index = build_metrics_index(session)
    metrics = metrics_index.get(detail.get("name", ""))

    return {"detail": detail, "devices": devices, "metrics": metrics or {}}


# ---------------------------------------------------------------------------
# Atlassian Document Format (ADF) helpers
# ---------------------------------------------------------------------------

def _text(text: str) -> dict:
    return {"type": "text", "text": text}


def _heading(level: int, text: str) -> dict:
    return {"type": "heading", "attrs": {"level": level}, "content": [_text(text)]}


def _paragraph(text: str) -> dict:
    return {"type": "paragraph", "content": [_text(text)]}


def _table_row(*cells, header=False) -> dict:
    cell_type = "tableHeader" if header else "tableCell"
    return {
        "type": "tableRow",
        "content": [
            {"type": cell_type, "content": [{"type": "paragraph", "content": [_text(str(c))]}]}
            for c in cells
        ],
    }


def _info_table(rows: list[tuple[str, str]]) -> dict:
    return {
        "type": "table",
        "attrs": {"isNumberColumnEnabled": False, "layout": "default"},
        "content": [_table_row("Field", "Value", header=True)] + [_table_row(k, v) for k, v in rows],
    }


# ---------------------------------------------------------------------------
# Section builders
# ---------------------------------------------------------------------------

def _teqtivity_section(info: dict) -> list:
    rows = [
        ("Model", info.get("model", "N/A")),
        ("Asset Tag", info.get("asset_tag", "N/A")),
        ("CPU", info.get("cpu", "N/A")),
        ("RAM", info.get("ram", "N/A")),
        ("Storage", info.get("storage", "N/A")),
        ("Deployment Date", info.get("deployment_date", "N/A")),
    ]
    return [_heading(4, "Asset Info (Teqtivity)"), _info_table(rows)]


def _fleet_section(host: dict) -> list:
    mdm = host.get("mdm") or {}
    battery = (host.get("batteries") or [{}])[0]
    total = host.get("gigs_total_disk_space", "N/A")
    avail = host.get("gigs_disk_space_available", "N/A")

    cpu_brand = host.get("cpu_brand", "")
    chip = cpu_brand.replace("Apple ", "") if cpu_brand else ""
    model_str = f"{fmt(host.get('hardware_model'))} ({chip})" if chip else fmt(host.get("hardware_model"))

    battery_str = fmt(battery.get("health"))
    if battery.get("cycle_count") is not None:
        battery_str += f", {battery['cycle_count']} cycles"

    vuln_software = [s for s in (host.get("software") or []) if s.get("vulnerabilities")]
    vuln_str = str(len(vuln_software))
    if vuln_software:
        names = ", ".join(f"{s['name']} {s['version']}" for s in vuln_software[:3])
        vuln_str += f" — {names}{'...' if len(vuln_software) > 3 else ''}"

    rows = [
        ("Model", model_str),
        ("OS Version", f"{fmt(host.get('os_version'))} ({fmt(host.get('build'))})"),
        ("Memory", fmt_bytes(host.get("memory"))),
        ("Disk", f"{avail} GB free / {total} GB total"),
        ("Uptime", fmt_ns(host.get("uptime"))),
        ("MDM Enrollment", mdm.get("enrollment_status", "N/A")),
        ("Battery Health", battery_str),
        ("Added to Fleet", fmt_date(host.get("created_at"))),
        ("Last MDM Check-in", fmt_datetime(host.get("last_mdm_checked_in_at"))),
        ("Software w/ Vulnerabilities", vuln_str),
    ]
    return [_heading(4, "Device Health (Fleet)"), _info_table(rows)]


def _device_section(serial: str, teqtivity: dict, fleet: dict | None) -> list:
    model = teqtivity.get("model", "Unknown")
    nodes = [_heading(3, f"{model}  |  Serial: {serial}")]
    nodes.extend(_teqtivity_section(teqtivity))
    if fleet:
        nodes.extend(_fleet_section(fleet))
    else:
        nodes.append(_paragraph("No Fleet record found for this serial number."))
    return nodes


def _zoom_section(room_name: str, info: dict) -> list:
    detail = info["detail"]
    devices = info["devices"]
    metrics = info["metrics"]

    health = metrics.get("health", "N/A")
    issues = [i for i in metrics.get("issues", []) if i]
    camera = metrics.get("camera", "N/A")
    mic = metrics.get("microphone", "N/A")
    speaker = metrics.get("speaker", "N/A")

    rows = [
        ("Room Name", detail.get("name", room_name)),
        ("Status", detail.get("status", "N/A")),
        ("Health", health),
        ("Issues", ", ".join(issues) if issues else "None"),
        ("Camera", camera),
        ("Microphone", mic),
        ("Speaker", speaker),
        ("Devices Connected", str(len(devices))),
    ]
    nodes = [_heading(3, f"Zoom Room: {detail.get('name', room_name)}"), _info_table(rows)]

    if devices:
        device_rows = [
            (d.get("device_type", "N/A"), d.get("status", "N/A"), d.get("device_hostname", "N/A"))
            for d in devices
        ]
        device_table = {
            "type": "table",
            "attrs": {"isNumberColumnEnabled": False, "layout": "default"},
            "content": [_table_row("Type", "Status", "Hostname", header=True)]
            + [_table_row(*r) for r in device_rows],
        }
        nodes.append(_heading(4, "Connected Devices"))
        nodes.append(device_table)

    return nodes


def build_comment_body(
    email: str,
    devices: list[tuple[str, dict, dict | None]],
    zoom_room_name: str | None,
    zoom_info: dict | None,
) -> dict:
    count = len(devices)
    content = [
        _heading(2, f"IT Onsite Info for {email}"),
        _heading(3, "User Devices"),
        _paragraph(f"{count} device{'s' if count != 1 else ''} found for this user."),
    ]
    for serial, teqtivity, fleet in devices:
        content.extend(_device_section(serial, teqtivity, fleet))

    if zoom_room_name:
        content.append(_heading(2, "Zoom Room"))
        if zoom_info:
            content.extend(_zoom_section(zoom_room_name, zoom_info))
        else:
            content.append(_paragraph(f'No Zoom room found matching "{zoom_room_name}".'))
    else:
        content.append(_heading(2, "Zoom Room"))
        content.append(_paragraph("No Zoom room name found in ticket description."))

    return {"type": "doc", "version": 1, "content": content}


def post_comment(issue_key: str, body: dict) -> str:
    url = f"{JIRA_BASE_URL}/rest/api/3/issue/{issue_key}/comment"
    response = requests.post(
        url,
        json={"body": body},
        headers={"Accept": "application/json", "Content-Type": "application/json"},
        auth=(JIRA_EMAIL, JIRA_API_TOKEN),
    )
    response.raise_for_status()
    return response.json()["id"]


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Post device + Zoom room info as a Jira comment based on the ticket reporter's email."
    )
    parser.add_argument("issue_key", help="Jira issue key, e.g. IT-123")
    args = parser.parse_args()

    validate_env()

    print(f"Fetching ticket {args.issue_key}...")
    issue = get_jira_issue(args.issue_key)
    email = extract_reporter_email(issue, args.issue_key)
    print(f"Reporter: {email}")

    description = get_description_text(issue)

    print("Extracting Zoom room name from description...")
    zoom_room_name = extract_zoom_room_name(description)
    if zoom_room_name:
        print(f"Zoom room identified: {zoom_room_name}")
    else:
        print("No Zoom room name found in description.")

    print("Looking up devices in Teqtivity...")
    raw_devices = get_devices_by_user(email)
    if not raw_devices:
        print("No devices found in Teqtivity for this user.")
        sys.exit(1)

    devices_data = []
    for d in raw_devices:
        cpu, ram, storage = parse_tech_specs(d.get("technical_specs", ""))
        serial = d.get("serial_no", "N/A")
        teqtivity_info = {
            "model": d.get("hardware_standard", "N/A"),
            "cpu": cpu,
            "ram": ram,
            "storage": storage,
            "deployment_date": d.get("date_deployed") or "N/A",
            "asset_tag": d.get("asset_tag") or "N/A",
        }

        fleet_info = None
        if serial and serial != "N/A":
            print(f"Looking up serial {serial} in Fleet...")
            try:
                host_summary = find_host_by_serial(serial)
                if host_summary:
                    fleet_info = get_host_details(host_summary["id"])
            except Exception as e:
                print(f"Warning: Fleet lookup failed for {serial}: {e}")

        devices_data.append((serial, teqtivity_info, fleet_info))

    zoom_info = None
    if zoom_room_name:
        print(f"Querying Zoom room '{zoom_room_name}'...")
        zoom_info = get_zoom_room_info(zoom_room_name)
        if not zoom_info:
            print(f"Warning: no Zoom room found matching '{zoom_room_name}'.")

    print("Posting comment to Jira...")
    body = build_comment_body(email, devices_data, zoom_room_name, zoom_info)
    comment_id = post_comment(args.issue_key, body)
    print(f"Done! Comment posted (ID: {comment_id})")


if __name__ == "__main__":
    main()
