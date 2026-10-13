import itertools
from datetime import date
from pathlib import Path

from scholaradar.labs import Institution, Lab, render_labs, university_database
from scholaradar.outreach import follow_up_due, render_outreach
from scholaradar.planner import build_plan, render_plan, write_plan_ics


def test_plan_orders_steps_and_adds_route_and_documents() -> None:
    items = build_plan(
        date(2027, 3, 1),
        "en",
        "embassy",
        ["academic transcript", "research plan"],
        today=date(2026, 10, 1),
    )
    assert items[-1].task == "Deadline" and items[-1].day == date(2027, 3, 1)
    assert any("embassy" in item.task.lower() for item in items)
    assert any(
        item.task == "Prepare: research plan" and item.day == date(2027, 1, 20)
        for item in items
    )
    assert all(a.day <= b.day for a, b in itertools.pairwise(items))


def test_plan_collapses_overdue_steps_into_catch_up() -> None:
    items = build_plan(
        date(2026, 10, 20), "mn", "unclear", [], today=date(2026, 10, 10)
    )
    assert items[0].day == date(2026, 10, 10) and items[0].task.startswith("Хоцорсон")
    assert all(item.day >= date(2026, 10, 10) for item in items)


def test_plan_outputs(tmp_path: Path) -> None:
    items = build_plan(
        date(2027, 3, 1), "en", "university", [], today=date(2026, 10, 1)
    )
    text = render_plan(
        "Global Korea Scholarship", date(2027, 3, 1), items, "en", "https://example.org"
    )
    assert (
        "# Application plan: Global Korea Scholarship" in text
        and "| 2027-03-01 | 0 | Deadline |" in text
    )
    ics = write_plan_ics(
        tmp_path / "plan.ics", "Global Korea Scholarship", items
    ).read_bytes()
    assert ics.count(b"BEGIN:VEVENT") == len(items)
    assert max(len(line) for line in ics.split(b"\r\n")) <= 75


def test_labs_render_and_database_links() -> None:
    institution = Institution("I201537933", "Tohoku University", "JP")
    lab = Lab(
        "A1",
        "Masayuki Kano",
        "Tohoku University",
        4,
        ["Recent advances in earthquake seismology using machine learning"],
        [2024],
        80,
        1200,
        "0000-0001-0000-0000",
        ["Seismology"],
    )
    text = render_labs(institution, [lab], "machine learning", 3)
    assert (
        "**Masayuki Kano**" in text
        and "r-info.tohoku.ac.jp" in text
        and "orcid.org/0000-0001-0000-0000" in text
    )
    assert "researchmap.jp/researchers?q=Masayuki+Kano" in text
    assert (
        university_database("Kyoto University") == "https://kdb.iimc.kyoto-u.ac.jp/en/"
    )
    assert university_database("Unknown College") == ""


def test_outreach_follow_up_rule() -> None:
    sent = {
        "id": 1,
        "professor": "Kano",
        "university": "Tohoku",
        "status": "sent",
        "sent_at": "2026-09-20T10:00:00+00:00",
        "replied_at": None,
        "note": "a|b",
    }
    fresh = dict(sent, id=2, sent_at="2026-10-05T10:00:00+00:00")
    assert follow_up_due(sent, date(2026, 10, 6)) and not follow_up_due(
        fresh, date(2026, 10, 6)
    )
    table = render_outreach([sent, fresh], date(2026, 10, 6))
    assert "| DUE |" in table and "a/b" in table


def test_models_dir_mounts_by_label_when_missing(tmp_path: Path, monkeypatch) -> None:
    from scholaradar.llm import server as server_module
    from scholaradar.llm.server import LlamaServer, LlamaSettings

    target = tmp_path / "drive" / "models" / "gguf"
    calls: list[list[str]] = []

    def fake_run(args, **kwargs):
        calls.append(list(args))
        target.mkdir(parents=True)

        class Result:
            stdout = "Mounted /dev/sda at /drive"
            stderr = ""

        return Result()

    monkeypatch.setattr(server_module.subprocess, "run", fake_run)
    settings = LlamaSettings(
        _env_file=None,
        models_dir=str(tmp_path / "drive*" / "models" / "gguf"),
        models_disk_label="HDD_2TB",
    )
    server = LlamaServer(tmp_path, settings)
    assert server.resolve_models_dir() == target
    assert calls == [["udisksctl", "mount", "-b", "/dev/disk/by-label/HDD_2TB"]]


def test_flag_altered_name() -> None:
    from scholaradar.drafting import flag_altered_name

    kept = "Hayashibe 先生\n\n突然のご連絡失礼いたします。"
    assert flag_altered_name(kept, "Mitsuhiro Hayashibe") == kept
    assert flag_altered_name("林部光弘先生\n\n...", "Mitsuhiro Hayashibe").startswith(
        "[CHECK: the professor's name"
    )
    assert (
        flag_altered_name("Dear Professor Tanaka", "田中 太郎")
        == "Dear Professor Tanaka"
    )
