import json
import os
import sys
import requests
from dotenv import load_dotenv

load_dotenv()

API_URL = os.getenv("TEQTIVITY_API_URL")
API_KEY = os.getenv("TEQTIVITY_API_KEY")


def validate_env():
    missing = [k for k, v in {"TEQTIVITY_API_URL": API_URL, "TEQTIVITY_API_KEY": API_KEY}.items() if not v]
    if missing:
        print(f"Error: missing environment variable(s): {', '.join(missing)}")
        print("Make sure your .env file is populated.")
        sys.exit(1)


def parse_tech_specs(specs: str) -> tuple[str, str, str]:
    if not specs or specs == "N/A":
        return "N/A", "N/A", "N/A"
    delimiter = " | " if " | " in specs else "/"
    parts = [p.strip() for p in specs.split(delimiter)]
    cpu = parts[0] if len(parts) > 0 else "N/A"
    ram = parts[1] if len(parts) > 1 else "N/A"
    storage = parts[2] if len(parts) > 2 else "N/A"
    return cpu, ram, storage


def get_devices_by_user(email: str) -> list[dict]:
    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    response = requests.get(f"{API_URL}/search-asset", headers=headers, params={"search": email})

    if not response.ok:
        print(f"Error {response.status_code}: {response.text}")
        sys.exit(1)

    data = response.json()
    return data.get("data", {}).get("items", [])


def main():
    validate_env()

    if len(sys.argv) >= 2:
        email = sys.argv[1]
    else:
        email = input("Enter username or email: ").strip()

    if not email:
        print("Error: email cannot be empty.")
        sys.exit(1)

    print(f"\nFetching devices for: {email}\n")
    devices = get_devices_by_user(email)

    if not devices:
        print("No devices found for this user.")
        return

    results = {}
    for d in devices:
        cpu, ram, storage = parse_tech_specs(d.get("technical_specs", ""))
        serial = d.get("serial_no", "N/A")
        results[serial] = {
            "model": d.get("hardware_standard", "N/A"),
            "cpu": cpu,
            "ram": ram,
            "storage": storage,
            "deployment_date": d.get("date_deployed") or "N/A",
            "asset_tag": d.get("asset_tag") or "N/A",
        }

    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
