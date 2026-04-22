import argparse
import json
import os
import sys

import requests
from dotenv import load_dotenv

load_dotenv()

JIRA_BASE_URL = os.getenv("JIRA_BASE_URL")
JIRA_EMAIL = os.getenv("JIRA_EMAIL")
JIRA_API_TOKEN = os.getenv("JIRA_API_TOKEN")

SOURCES = ["Teqtivity", "Fleet", "Zoom"]


def format_section(source: str, data: dict) -> list:
    nodes = [
        {"type": "heading", "attrs": {"level": 3}, "content": [{"type": "text", "text": source}]}
    ]
    rows = [
        {
            "type": "tableRow",
            "content": [
                {"type": "tableHeader", "content": [{"type": "paragraph", "content": [{"type": "text", "text": "Field"}]}]},
                {"type": "tableHeader", "content": [{"type": "paragraph", "content": [{"type": "text", "text": "Value"}]}]},
            ],
        }
    ]
    for key, value in data.items():
        rows.append({
            "type": "tableRow",
            "content": [
                {"type": "tableCell", "content": [{"type": "paragraph", "content": [{"type": "text", "text": str(key)}]}]},
                {"type": "tableCell", "content": [{"type": "paragraph", "content": [{"type": "text", "text": str(value)}]}]},
            ],
        })
    nodes.append({"type": "table", "content": rows})
    return nodes


def build_body(sections: dict) -> dict:
    content = []
    for source, data in sections.items():
        content.extend(format_section(source, data))
    return {"type": "doc", "version": 1, "content": content}


def add_comment(issue_key: str, body: dict) -> dict:
    url = f"{JIRA_BASE_URL}/rest/api/3/issue/{issue_key}/comment"
    headers = {"Accept": "application/json", "Content-Type": "application/json"}
    response = requests.post(
        url,
        json={"body": body},
        headers=headers,
        auth=(JIRA_EMAIL, JIRA_API_TOKEN),
    )
    response.raise_for_status()
    return response.json()


def parse_args():
    parser = argparse.ArgumentParser(
        description="Add a combined Jira comment from Teqtivity, Fleet, and Zoom JSON (newline-delimited via stdin)."
    )
    parser.add_argument("issue_key", help="Jira issue key, e.g. PROJ-123")
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()

    lines = [line.strip() for line in sys.stdin.read().splitlines() if line.strip()]
    if len(lines) != 3:
        print(f"Error: expected 3 newline-delimited JSON objects, got {len(lines)}", file=sys.stderr)
        sys.exit(1)

    sections = {}
    for source, line in zip(SOURCES, lines):
        try:
            sections[source] = json.loads(line)
        except json.JSONDecodeError as e:
            print(f"Error parsing {source} JSON: {e}", file=sys.stderr)
            sys.exit(1)

    body = build_body(sections)
    result = add_comment(args.issue_key, body)
    print(f"Comment added successfully: {result['id']}")
