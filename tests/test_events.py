from datetime import date
from kabu.events import load_events, upcoming, imminent_high, needs_review, events_lines

CSV = """date,end_date,event,importance,note,checked
2026-12-08,2026-12-10,FOMC,高,年間日程,2026-11-10
2026-12-11,,SQ,中,,2026-11-10
2026-12-17,2026-12-18,日銀会合,高,,
2027-01-20,,遠い予定,中,,2026-11-10
bad,,壊れた行,高,,
"""


def ev(tmp_path):
    p = tmp_path / "events.csv"
    p.write_text(CSV, encoding="utf-8")
    return load_events(p)


def test_load_skips_bad_rows_and_sorts(tmp_path):
    e = ev(tmp_path)
    assert [x["event"] for x in e] == ["FOMC", "SQ", "日銀会合", "遠い予定"]
    assert e[0]["end"] == date(2026, 12, 10) and e[1]["end"] == date(2026, 12, 11)


def test_upcoming_two_weeks(tmp_path):
    names = [x["event"] for x in upcoming(ev(tmp_path), date(2026, 12, 7))]
    assert names == ["FOMC", "SQ", "日銀会合"]


def test_imminent_high_covers_day_before_and_span(tmp_path):
    e = ev(tmp_path)
    assert [x["event"] for x in imminent_high(e, date(2026, 12, 7))] == ["FOMC"]   # 前日
    assert [x["event"] for x in imminent_high(e, date(2026, 12, 10))] == ["FOMC"]  # 結果判明日
    assert imminent_high(e, date(2026, 12, 11)) == []
    assert [x["event"] for x in imminent_high(e, date(2026, 12, 16))] == ["日銀会合"]


def test_needs_review_after_seven_days(tmp_path):
    e = ev(tmp_path)
    assert not needs_review(e, date(2026, 11, 16))
    assert needs_review(e, date(2026, 11, 17))
    assert needs_review([], date(2026, 11, 10))


def test_events_lines(tmp_path):
    text = "\n".join(events_lines(ev(tmp_path), date(2026, 12, 7)))
    assert "12/08〜12/10 FOMC（重要度：高）" in text
    assert "日銀会合（重要度：高）【要確認" in text
    assert "今日〜明日に重要イベント（FOMC）" in text
    assert "最終確認日：2026-11-10" in text and "更新すること" in text
    assert "遠い予定" not in text


def test_events_lines_empty():
    text = "\n".join(events_lines([], date(2026, 11, 10)))
    assert "登録されたイベントはありません" in text and "未確認" in text


def test_checked_must_be_a_date(tmp_path):
    p = tmp_path / "events.csv"
    p.write_text("date,end_date,event,importance,note,checked\n2026-12-08,,X,高,備考,900億円枠\n", encoding="utf-8")
    e = load_events(p)
    assert e[0]["checked"] == "" and needs_review(e, date(2026, 11, 10))


def test_real_events_csv_has_no_broken_rows():
    e = load_events("data/events.csv")
    assert e and all(x["checked"] for x in e), [x["event"] for x in e if not x["checked"]]
    assert all(x["importance"] in ("高", "中", "低") for x in e)
