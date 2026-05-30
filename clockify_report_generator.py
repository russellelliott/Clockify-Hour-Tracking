import importlib
import json
import os
from datetime import date, datetime, time, timezone
from pathlib import Path

import requests

DEFAULT_API_BASE = "https://api.clockify.me/api/v1"
DEFAULT_PAGE_SIZE = 5000
REPORTS_DIR = Path("reports")
HISTORY_FILE = REPORTS_DIR / "report_history.json"


def load_environment(path: str = ".env"):
    try:
        dotenv_module = importlib.import_module("dotenv")
        dotenv_module.load_dotenv(dotenv_path=path, override=False)
        return
    except ImportError:
        pass

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


def _parse_history_date(value: str) -> date:
    try:
        return datetime.fromisoformat(value).date()
    except ValueError:
        return datetime.strptime(value, "%Y-%m-%d").date()


def get_default_date_range():
    history = load_report_history()
    if history:
        latest_report = max(history, key=lambda item: item.get("endDate", ""))
        end_value = latest_report.get("endDate")
        if end_value:
            start_date = _parse_history_date(end_value)
            return start_date, date.today()

    today = date.today()
    return today, today


def load_report_history():
    if not HISTORY_FILE.exists():
        return []

    with HISTORY_FILE.open("r", encoding="utf-8") as file_handle:
        data = json.load(file_handle)

    if isinstance(data, dict):
        return data.get("reports", [])
    if isinstance(data, list):
        return data
    return []


def save_report_history(history):
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    with HISTORY_FILE.open("w", encoding="utf-8") as file_handle:
        json.dump({"reports": history}, file_handle, indent=2)


def duration_seconds(entry: dict) -> float:
    interval = entry.get("timeInterval", {})
    start = interval.get("start")
    end = interval.get("end")
    if not start or not end:
        return 0.0
    start_dt = datetime.fromisoformat(start.replace("Z", "+00:00"))
    end_dt = datetime.fromisoformat(end.replace("Z", "+00:00"))
    return max(0.0, (end_dt - start_dt).total_seconds())


def iso_z(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _midnight_utc(value: date) -> datetime:
    return datetime.combine(value, time.min, tzinfo=timezone.utc)


def _end_of_day_utc(value: date) -> datetime:
    return datetime.combine(value, time(23, 59, 59, 999000), tzinfo=timezone.utc)


def _build_filename(start_date: date, end_date: date) -> str:
    return f"clockify_report_{start_date.isoformat()}_to_{end_date.isoformat()}.json"


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


def generate_report(start_date: date, end_date: date):
    load_environment()

    api_key = os.getenv("CLOCKIFY_API_KEY")
    workspace_id = os.getenv("CLOCKIFY_WORKSPACE_ID")
    api_base = os.getenv("CLOCKIFY_API_BASE", DEFAULT_API_BASE).rstrip("/")
    page_size = int(os.getenv("CLOCKIFY_PAGE_SIZE", str(DEFAULT_PAGE_SIZE)))

    if not api_key or not workspace_id:
        raise ValueError("Set CLOCKIFY_API_KEY and CLOCKIFY_WORKSPACE_ID in your .env file")

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)

    headers = {
        "X-Api-Key": api_key,
        "Content-Type": "application/json",
    }

    start_dt = _midnight_utc(start_date)
    end_dt = _end_of_day_utc(end_date)

    user = get_current_user(headers, api_base)
    user_id = user["id"]
    entries = get_time_entries(headers, api_base, workspace_id, user_id, iso_z(start_dt), iso_z(end_dt), page_size)
    total_seconds = sum(duration_seconds(entry) for entry in entries)

    file_name = _build_filename(start_date, end_date)
    file_path = REPORTS_DIR / file_name

    report_data = {
        "workspaceId": workspace_id,
        "userId": user_id,
        "start": iso_z(start_dt),
        "end": iso_z(end_dt),
        "entriesCount": len(entries),
        "totalSeconds": round(total_seconds, 2),
        "totalHours": round(total_seconds / 3600, 2),
        "entries": entries,
    }

    with file_path.open("w", encoding="utf-8") as file_handle:
        json.dump(report_data, file_handle, indent=2)

    history = load_report_history()
    history.append(
        {
            "startDate": start_date.isoformat(),
            "endDate": end_date.isoformat(),
            "fileName": file_name,
            "filePath": str(file_path),
            "generatedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
    )
    save_report_history(history)

    return {
        "fileName": file_name,
        "filePath": str(file_path),
        "historyFile": str(HISTORY_FILE),
        "workspaceId": workspace_id,
        "userId": user_id,
        "start": iso_z(start_dt),
        "end": iso_z(end_dt),
        "entriesCount": len(entries),
        "totalHours": round(total_seconds / 3600, 2),
    }
