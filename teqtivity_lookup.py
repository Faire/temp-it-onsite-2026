#!/usr/bin/env python3
import argparse
import subprocess
import sys

import requests

BASE_URL = "https://faire.teqtivity.com"
ASSETS_ENDPOINT = f"{BASE_URL}/api/search-asset"

# TODO: update to match the exact 1Password item name storing the Teqtivity API credential
OP_ITEM_NAME = "Teqtivity"
# OP_VAULT = "IT"  # uncomment and set if you need to target a specific vault


def get_api_key():
    import os
    if os.environ.get("TEQTIVITY_API_KEY"):
        return os.environ["TEQTIVITY_API_KEY"]

    cmd = ["op", "item", "get", OP_ITEM_NAME, "--fields", "credential"]
    # cmd = ["op", "item", "get", OP_ITEM_NAME, "--vault", OP_VAULT, "--fields", "credential"]
    try:
        result = subprocess.check_output(cmd, stderr=subprocess.DEVNULL)
        return result.decode().strip()
    except FileNotFoundError:
        print("Error: 1Password CLI ('op') not found. Install it from https://developer.1password.com/docs/cli/")
        print("       Or set the TEQTIVITY_API_KEY environment variable to bypass 1Password.")
        sys.exit(1)
    except subprocess.CalledProcessError:
        print(f"Error: Could not retrieve '{OP_ITEM_NAME}' from 1Password. Ensure you're signed in ('op signin') and the item name is correct.")
        sys.exit(1)


def lookup_user_assets(email_or_username, api_key):
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Accept": "application/json",
    }
    params = {"search": email_or_username}

    try:
        response = requests.get(ASSETS_ENDPOINT, headers=headers, params=params, timeout=10)
        if "--debug" in sys.argv:
            print(f"[debug] GET {response.url}")
            print(f"[debug] Status: {response.status_code}")
            print(f"[debug] Response: {response.text[:1000]}")
        response.raise_for_status()
    except requests.exceptions.HTTPError:
        print(f"Error: HTTP {response.status_code} — {response.text}")
        sys.exit(1)
    except requests.exceptions.ConnectionError:
        print(f"Error: Could not connect to {BASE_URL}. Check the base URL and your network connection.")
        sys.exit(1)
    except requests.exceptions.Timeout:
        print("Error: Request timed out.")
        sys.exit(1)

    return response.json()


def display_assets(data, email_or_username):
    assets = (data.get("data") or {}).get("items", [])

    if not assets:
        print(f"No assets found for: {email_or_username}")
        return

    for i, asset in enumerate(assets, start=1):
        if len(assets) > 1:
            print(f"\n--- Asset {i} ---")

        specs = [s.strip() for s in asset.get("technical_specs", "").split("|")]
        cpu = specs[0] if len(specs) > 0 else "N/A"
        ram = specs[1] if len(specs) > 1 else "N/A"

        print(f"  Model:           {asset.get('hardware_standard', 'N/A')}")
        print(f"  Serial Number:   {asset.get('serial_no', 'N/A')}")
        print(f"  CPU:             {cpu}")
        print(f"  RAM:             {ram}")
        print(f"  Deployment Date: {asset.get('date_deployed') or asset.get('first_assigned_date') or 'N/A'}")


def main():
    parser = argparse.ArgumentParser(
        description="Look up Teqtivity asset info for a user by email or username."
    )
    parser.add_argument("email_or_username", help="User email or username to look up")
    parser.add_argument("--debug", action="store_true", help="Print raw API request and response")
    args = parser.parse_args()

    api_key = get_api_key()
    data = lookup_user_assets(args.email_or_username, api_key)
    display_assets(data, args.email_or_username)


if __name__ == "__main__":
    main()
