import argparse
import os
import sys

import requests
from dotenv import load_dotenv

load_dotenv()

API_URL = os.getenv("TEQTIVITY_API_URL", "").rstrip("/")
API_KEY = os.getenv("TEQTIVITY_API_KEY", "")


def build_session() -> requests.Session:
    if not API_URL or not API_KEY:
        sys.exit("Error: TEQTIVITY_API_URL and TEQTIVITY_API_KEY must be set in .env")
    session = requests.Session()
    session.headers.update({"Authorization": API_KEY, "Accept": "application/json"})
    return session


def search_assets(session: requests.Session, query: str) -> list[dict]:
    resp = session.get(f"{API_URL}/search-asset", params={"search": query})
    if resp.status_code != 200:
        sys.exit(f"Error fetching assets ({resp.status_code}): {resp.text}")
    return resp.json().get("data", {}).get("items", [])


def print_results(query: str, assets: list[dict]) -> None:
    if not assets:
        print(f"No assets found for '{query}'.")
        return

    user_details = assets[0].get("user_details", {})
    name = f"{user_details.get('first_name', '')} {user_details.get('last_name', '')}".strip()
    email = user_details.get("email", "N/A")

    print(f"\nUser: {name}  |  Email: {email}")
    print("-" * 60)
    print(f"{'Asset Tag':<12} {'Model':<40} {'Serial':<20} {'Status':<12} {'Assigned'}")
    print("-" * 105)

    for asset in assets:
        tag = asset.get("asset_tag", "N/A")
        model = asset.get("hardware_standard", "N/A")
        serial = asset.get("serial_no", "N/A")
        status = asset.get("asset_status", "N/A")
        assigned = asset.get("first_assigned_date", "N/A")
        print(f"{tag:<12} {model:<40} {serial:<20} {status:<12} {assigned}")

    print(f"\nTotal devices: {len(assets)}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Look up a user's devices in Teqtivity.")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--email", help="User's email address")
    group.add_argument("--name", help="User's full name")
    args = parser.parse_args()

    session = build_session()
    query = args.email or args.name
    assets = search_assets(session, query)
    print_results(query, assets)


if __name__ == "__main__":
    main()
