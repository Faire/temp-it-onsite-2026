"""
Meta-script: uses Claude API to generate zoom_room_info.py.
Run: python generate_zoom_script.py
Output: zoom_room_info.py (the Zoom API integration script)
"""

import os
import anthropic
from dotenv import load_dotenv

load_dotenv()

SYSTEM_PROMPT = """You are an expert Python developer. When asked to write a script, output ONLY raw Python code with no markdown fences, no explanation, and no commentary before or after the code."""

USER_PROMPT = """Write a Python script called zoom_room_info.py that does the following:

1. Loads these environment variables from a .env file using python-dotenv:
   - ZOOM_ACCOUNT_ID
   - ZOOM_CLIENT_ID
   - ZOOM_CLIENT_SECRET

2. Accepts a single CLI argument: a Zoom Room Name or Room ID (string).

3. Authenticates with Zoom using Server-to-Server OAuth:
   - POST https://zoom.us/oauth/token
   - Use HTTP Basic Auth with client_id:client_secret
   - Body: grant_type=account_credentials&account_id={ZOOM_ACCOUNT_ID}
   - Extract the access_token from the response

4. If the input looks like a room name (not an ID), resolve it to a room ID:
   - GET https://api.zoom.us/v2/rooms?search_key={name}&page_size=10
   - Match the first result whose name equals the input (case-insensitive)
   - Raise a clear error if no match is found

5. Fetch room details and status:
   - GET https://api.zoom.us/v2/rooms/{roomId}
   - Extract: room_name, status (e.g. Available, InMeeting, Offline)

6. Fetch device information:
   - GET https://api.zoom.us/v2/rooms/{roomId}/devices
   - For each device, extract: device_name, device_type (Camera/Microphone/Speaker), status

7. Fetch live room status from dashboard metrics:
   - GET https://api.zoom.us/v2/metrics/zoomrooms?page_size=100
   - Find the entry matching roomId
   - Extract live_status if available (use as fallback status)

8. Fetch scheduled meetings:
   - GET https://api.zoom.us/v2/rooms/{roomId}/meetings
   - Extract for each: topic, start_time, duration (minutes), meeting_id

9. Assemble and print (via json.dumps with indent=2) a dictionary with this structure:
{
  "room_id": "...",
  "room_name": "...",
  "status": "...",
  "devices": {
    "cameras": [{"name": "...", "status": "..."}],
    "microphones": [{"name": "...", "status": "..."}],
    "speakers": [{"name": "...", "status": "..."}]
  },
  "scheduled_meetings": [
    {"meeting_id": "...", "topic": "...", "start_time": "...", "duration_min": 0}
  ]
}

10. Also return the dictionary from a function get_room_info(room_input: str) -> dict so the script is importable.

Use the requests library. Handle HTTP errors by raising a RuntimeError with the status code and response text. Use argparse for the CLI."""

def main():
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY not set in environment or .env file")

    client = anthropic.Anthropic(api_key=api_key)

    print("Calling Claude API to generate zoom_room_info.py ...")

    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=4096,
        system=[
            {
                "type": "text",
                "text": SYSTEM_PROMPT,
                "cache_control": {"type": "ephemeral"},
            }
        ],
        messages=[{"role": "user", "content": USER_PROMPT}],
    )

    generated_code = message.content[0].text.strip()

    output_path = "zoom_room_info.py"
    with open(output_path, "w") as f:
        f.write(generated_code)

    print(f"Generated {output_path} ({len(generated_code)} chars)")
    print(f"Input tokens: {message.usage.input_tokens}, Output tokens: {message.usage.output_tokens}")
    print(f"\nUsage:\n  python {output_path} \"Your Zoom Room Name\"")


if __name__ == "__main__":
    main()
