"""Tests for _extract_report_media helper."""

from pathlib import Path

from secbot.agent.loop import _extract_report_media


def test_extract_from_tool_result_json(tmp_path: Path) -> None:
    report_file = tmp_path / "report.html"
    report_file.write_text("<html>test</html>", encoding="utf-8")

    all_msgs = [
        {
            "role": "tool",
            "tool_call_id": "call_1",
            "name": "delegate_task",
            "content": f'{{"report_path": "{report_file}", "status": "ok"}}',
        }
    ]
    result = _extract_report_media(all_msgs, "Report done.")
    assert result == [str(report_file)]


def test_extract_null_report_path_ignored(tmp_path: Path) -> None:
    all_msgs = [
        {
            "role": "tool",
            "content": '{"report_path": "null", "status": "empty"}',
        }
    ]
    result = _extract_report_media(all_msgs, "Nothing found.")
    assert result == []


def test_extract_from_final_content(tmp_path: Path) -> None:
    report_file = tmp_path / "report.html"
    report_file.write_text("<html>test</html>", encoding="utf-8")

    all_msgs: list[dict] = []
    final = f"Report saved to {report_file}"
    result = _extract_report_media(all_msgs, final)
    assert result == [str(report_file)]


def test_missing_file_ignored(tmp_path: Path) -> None:
    missing = tmp_path / "missing.html"
    all_msgs = [
        {
            "role": "tool",
            "content": f'{{"report_path": "{missing}", "status": "ok"}}',
        }
    ]
    result = _extract_report_media(all_msgs, "Done.")
    assert result == []


def test_non_tool_role_ignored(tmp_path: Path) -> None:
    report_file = tmp_path / "report.html"
    report_file.write_text("<html>test</html>", encoding="utf-8")

    all_msgs = [
        {
            "role": "assistant",
            "content": f'{{"report_path": "{report_file}"}}',
        }
    ]
    result = _extract_report_media(all_msgs, "Done.")
    assert result == []


def test_multiple_reports_deduped(tmp_path: Path) -> None:
    r1 = tmp_path / "report1.html"
    r2 = tmp_path / "report2.html"
    r1.write_text("a", encoding="utf-8")
    r2.write_text("b", encoding="utf-8")

    all_msgs = [
        {
            "role": "tool",
            "content": f'{{"report_path": "{r1}", "status": "ok"}}',
        },
        {
            "role": "tool",
            "content": f'{{"report_path": "{r2}", "status": "ok"}}',
        },
    ]
    result = _extract_report_media(all_msgs, f"Also see {r1}")
    assert result == [str(r1), str(r2)]
