import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def run_state_expression(expression: str) -> object:
    script = f"""
const state = require(process.argv[1]);
const result = {expression};
process.stdout.write(JSON.stringify(result));
"""
    result = subprocess.run(
        ["node", "-e", script, str(ROOT / "assets" / "runtime-view-state.js")],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(result.stdout)


def test_today_uses_the_browser_local_calendar_date() -> None:
    result = run_state_expression(
        "state.localDate(new Date(2026, 8, 10, 23, 30, 0))"
    )

    assert result == "2026-09-10"


def test_environment_switch_resets_stale_date_to_today() -> None:
    result = run_state_expression(
        "(() => { const value = { date: '2026-08-22', dateManuallySet: true }; "
        "state.resetDateToToday(value, new Date(2026, 8, 10, 12, 0, 0)); return value; })()"
    )

    assert result == {"date": "2026-09-10", "dateManuallySet": False}


def test_scroll_top_button_only_appears_beyond_one_viewport() -> None:
    result = run_state_expression(
        "[state.shouldShowScrollTop(799, 800), "
        "state.shouldShowScrollTop(800, 800), "
        "state.shouldShowScrollTop(801, 800)]"
    )

    assert result == [False, False, True]
