import flet as ft
from datetime import date, datetime

from clockify_report_generator import generate_report, get_default_date_range, load_report_history


def _format_date(value: date) -> str:
    return value.strftime("%b %d, %Y")


def _format_history_date(value: str) -> str:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        parsed = datetime.strptime(value, "%Y-%m-%d")
    return parsed.strftime("%b %d, %Y")


def _coerce_selected_date(value) -> date:
    if isinstance(value, date):
        return value
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, str):
        return datetime.strptime(value.strip(), "%Y-%m-%d").date()
    raise ValueError("Unsupported date value")


def _format_history_item(item: dict) -> str:
    return f"{_format_history_date(item['startDate'])} to {_format_history_date(item['endDate'])} -> {item['fileName']}"


def _build_history_text() -> str:
    history = load_report_history()
    if not history:
        return "No reports generated yet."

    recent_items = history[-5:][::-1]
    return "\n".join(_format_history_item(item) for item in recent_items)


def main(page: ft.Page):
    page.title = "Clockify Report Generator"
    page.window_width = 720
    page.window_height = 560
    page.padding = 24
    page.scroll = ft.ScrollMode.AUTO
    page.theme_mode = ft.ThemeMode.LIGHT

    default_start, default_end = get_default_date_range()
    start_date = default_start
    end_date = default_end

    start_button_label = ft.Text(_format_date(start_date))
    end_button_label = ft.Text(_format_date(end_date))

    start_button = ft.ElevatedButton(content=start_button_label)
    end_button = ft.ElevatedButton(content=end_button_label)

    start_picker = ft.DatePicker()
    end_picker = ft.DatePicker()

    def open_start_picker(_):
        start_picker.value = start_date
        start_picker.open = True
        page.update()

    def open_end_picker(_):
        end_picker.value = end_date
        end_picker.open = True
        page.update()

    start_button.on_click = open_start_picker
    end_button.on_click = open_end_picker

    def on_start_changed(_):
        nonlocal start_date
        selected = _coerce_selected_date(start_picker.value)
        start_date = selected
        start_button_label.value = _format_date(start_date)
        page.update()

    def on_end_changed(_):
        nonlocal end_date
        selected = _coerce_selected_date(end_picker.value)
        end_date = selected
        end_button_label.value = _format_date(end_date)
        page.update()

    start_picker.on_change = on_start_changed
    end_picker.on_change = on_end_changed
    page.overlay.extend([start_picker, end_picker])

    status_text = ft.Text(
        "Choose a start and end date, then generate a JSON report.",
        selectable=True,
    )
    history_text = ft.Text(_build_history_text(), selectable=True)
    dialog_holder = {"dialog": None}

    def show_dialog(title: str, message: str):
        dialog_holder["dialog"] = ft.AlertDialog(
            title=ft.Text(title),
            content=ft.Text(message, selectable=True),
        )
        page.dialog = dialog_holder["dialog"]
        dialog_holder["dialog"].open = True
        page.update()

    def refresh_history():
        history_text.value = _build_history_text()

    def generate_clicked(_):
        if start_date > end_date:
            show_dialog("Invalid range", "The start date must be on or before the end date.")
            return

        status_text.value = "Generating report..."
        page.update()

        try:
            result = generate_report(start_date, end_date)
        except Exception as exc:
            status_text.value = "Report generation failed."
            page.update()
            show_dialog("Report generation failed", str(exc))
            return

        status_text.value = f"Saved {result['fileName']} in reports/"
        refresh_history()
        page.update()
        show_dialog(
            "Report generated",
            f"Saved report to:\n{result['filePath']}\n\nHistory file:\n{result['historyFile']}",
        )

    page.add(
        ft.Column(
            [
                ft.Text("Clockify Report Generator", size=24, weight=ft.FontWeight.BOLD),
                status_text,
                ft.Row(
                    [
                        ft.Column(
                            [
                                ft.Text("Start date"),
                                start_button,
                            ],
                            spacing=8,
                        ),
                        ft.Column(
                            [
                                ft.Text("End date"),
                                end_button,
                            ],
                            spacing=8,
                        ),
                    ],
                    spacing=16,
                ),
                ft.Row([ft.ElevatedButton("Generate JSON Report", on_click=generate_clicked)]),
                ft.Divider(),
                ft.Text("Recent reports", size=16, weight=ft.FontWeight.BOLD),
                history_text,
            ],
            spacing=16,
            expand=True,
        )
    )


if __name__ == "__main__":
    ft.app(target=main)
