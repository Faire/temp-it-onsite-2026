import os
import requests
from dotenv import load_dotenv

load_dotenv()

JIRA_BASE_URL = os.getenv("JIRA_BASE_URL")
JIRA_EMAIL = os.getenv("JIRA_EMAIL")
JIRA_API_TOKEN = os.getenv("JIRA_API_TOKEN")


def add_comment(issue_key: str, comment: str) -> dict:
    url = f"{JIRA_BASE_URL}/rest/api/3/issue/{issue_key}/comment"
    headers = {"Accept": "application/json", "Content-Type": "application/json"}
    payload = {
        "body": {
            "type": "doc",
            "version": 1,
            "content": [
                {
                    "type": "paragraph",
                    "content": [{"type": "text", "text": comment}],
                }
            ],
        }
    }

    response = requests.post(
        url,
        json=payload,
        headers=headers,
        auth=(JIRA_EMAIL, JIRA_API_TOKEN),
    )
    response.raise_for_status()
    return response.json()


if __name__ == "__main__":
    issue_key = input("Enter Jira issue key (e.g. PROJ-123): ").strip()
    comment = input("Enter comment: ").strip()
    result = add_comment(issue_key, comment)
    print(f"Comment added successfully: {result['id']}")
