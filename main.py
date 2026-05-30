#!/usr/bin/env python3
import argparse
import importlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests

DEFAULT_API_BASE = "https://api.clockify.me/api/v1"
DEFAULT_PAGE_SIZE = 5000


def load_environment(path: str = ".env"):
    try:
        dotenv_module = importlib.import_module("dotenv")
        dotenv_module.load_dotenv(dotenv_path=path, override=False)
        return
    except ImportError:
        pass

    # Fallback loader if python-dotenv is not installed.
    env_path = Path(path)
    if not env_path.exists():
        return
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def parse_date(value: str) -> datetime:
    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%SZ"):
        try:
            dt = datetime.strptime(value, fmt)
            return dt.replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    raise argparse.ArgumentTypeError(
        f"Invalid date '{value}'. Use YYYY-MM-DD or UTC ISO like 2026-05-01T00:00:00Z"
    )


def iso_z(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def get_current_user(headers: dict, api_base: str):
    response = requests.get(f"{api_base}/user", headers=headers, timeout=60)
    response.raise_for_status()
    return response.json()


def get_time_entries(headers: dict, api_base: str, workspace_id: str, user_id: str, start: str, end: str, page_size: int):
    entries = []
    page = 1

    while True:
        response = requests.get(
            f"{api_base}/workspaces/{workspace_id}/user/{user_id}/time-entries",
            headers=headers,
            params={
                "start": start,
                "end": end,
                "page": page,
                "page-size": page_size,
            },
            timeout=60,
        )
        response.raise_for_status()
        data = response.json()
        if not data:
            break
        entries.extend(data)

        last_page = response.headers.get("Last-Page", "true").lower() == "true"
        if last_page:
            break
        page += 1

    return entries


def duration_seconds(entry: dict) -> float:
    interval = entry.get("timeInterval", {})
    start = interval.get("start")
    end = interval.get("end")
    if not start or not end:
        return 0.0
    start_dt = datetime.fromisoformat(start.replace("Z", "+00:00"))
    end_dt = datetime.fromisoformat(end.replace("Z", "+00:00"))
    return max(0.0, (end_dt - start_dt).total_seconds())


def main():
    parser = argparse.ArgumentParser(description="Fetch all Clockify time entries between two dates for the current user.")
    parser.add_argument("--start", required=True, type=parse_date, help="Start date, e.g. 2026-05-01")
    parser.add_argument("--end", required=True, type=parse_date, help="End date, e.g. 2026-05-31")
    parser.add_argument("--env-file", default=".env", help="Path to .env file, default: .env")
    parser.add_argument("--output", default="clockify_time_entries.json", help="Output JSON file")
    args = parser.parse_args()

    load_environment(args.env_file)
    api_key = os.getenv("CLOCKIFY_API_KEY")
    workspace_id = os.getenv("CLOCKIFY_WORKSPACE_ID")
    api_base = os.getenv("CLOCKIFY_API_BASE", DEFAULT_API_BASE).rstrip("/")
    page_size = int(os.getenv("CLOCKIFY_PAGE_SIZE", str(DEFAULT_PAGE_SIZE)))

    if not api_key or not workspace_id:
        parser.error("Set CLOCKIFY_API_KEY and CLOCKIFY_WORKSPACE_ID in your .env file")

    start = args.start.replace(hour=0, minute=0, second=0, microsecond=0)
    end = args.end.replace(hour=23, minute=59, second=59, microsecond=999000)

    headers = {
        "X-Api-Key": api_key,
        "Content-Type": "application/json",
    }

    user = get_current_user(headers, api_base)
    user_id = user["id"]
    entries = get_time_entries(headers, api_base, workspace_id, user_id, iso_z(start), iso_z(end), page_size)
    total_seconds = sum(duration_seconds(entry) for entry in entries)

    result = {
        "workspaceId": workspace_id,
        "userId": user_id,
        "start": iso_z(start),
        "end": iso_z(end),
        "entriesCount": len(entries),
        "totalSeconds": round(total_seconds, 2),
        "totalHours": round(total_seconds / 3600, 2),
        "entries": entries,
    }

    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2)

    print(json.dumps({
        "workspaceId": workspace_id,
        "userId": user_id,
        "start": iso_z(start),
        "end": iso_z(end),
        "entriesCount": len(entries),
        "totalHours": round(total_seconds / 3600, 2),
        "output": args.output,
    }, indent=2))


if __name__ == "__main__":
    try:
        main()
    except requests.HTTPError as e:
        status = e.response.status_code if e.response is not None else "unknown"
        body = e.response.text[:1000] if e.response is not None else str(e)
        print(json.dumps({"error": "Clockify API request failed", "status": status, "details": body}, indent=2), file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(json.dumps({"error": str(e)}, indent=2), file=sys.stderr)
        sys.exit(1)