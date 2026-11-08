import json
from datetime import date
from kabu.prepare import run


def test_prepare_writes_daily_files(tmp_path):
    calls = []
    def fake_settle(today, data_dir):
        calls.append(("settle", today))
        return {"today": today.isoformat(), "status": "ok", "holdings": [], "total": 1}
    def fake_build(root, today):
        calls.append(("build", today))
        return "# md", {"today": today, "market": []}
    res = run(tmp_path, date(2026, 11, 10), settle_fn=fake_settle, build_fn=fake_build)
    d = tmp_path / "data" / "daily" / "2026-11-10"
    assert res["status"] == "ok"
    assert json.loads((d / "settle.json").read_text(encoding="utf-8"))["status"] == "ok"
    assert (d / "briefing.md").read_text(encoding="utf-8") == "# md"
    assert json.loads((d / "briefing.json").read_text(encoding="utf-8"))["today"] == "2026-11-10"
    assert [c[0] for c in calls] == ["settle", "build"]


def test_prepare_holiday_skips_briefing(tmp_path):
    res = run(tmp_path, date(2026, 11, 8),
              settle_fn=lambda t, d: {"today": t.isoformat(), "status": "holiday"},
              build_fn=lambda r, t: (_ for _ in ()).throw(AssertionError("should not build")))
    assert res["status"] == "holiday"
    assert not (tmp_path / "data" / "daily" / "2026-11-08" / "briefing.md").exists()
