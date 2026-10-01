"""Scheduler scoring math: daily averages, 7-day business score, empty = None."""

import sqlite3

import pytest

from app import config, db
from app.scheduler import business_score, daily_scores


@pytest.fixture()
def tmpdb(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", str(tmp_path / "test.db"))
    db.init_db()
    uid = db.create_user("t@example.com", "hash")
    biz = db.create_business(uid, "Biz", "https://biz.example.com", ["p1"])
    return biz


def _backdate_check(biz_id, score, day_ago):
    from datetime import datetime, timedelta, timezone
    conn = sqlite3.connect(config.DB_PATH)
    try:
        ts = (datetime.now(timezone.utc) - timedelta(days=day_ago)).isoformat()
        conn.execute(
            "INSERT INTO checks (business_id, provider_ai, phrase, answer_text,"
            " mention_bool, competitors, score, ran_at)"
            " VALUES (?, 'openai', 'p1', 'a', 1, '[]', ?, ?)",
            (biz_id, score, ts))
        conn.commit()
    finally:
        conn.close()


def test_daily_scores_average_per_day(tmpdb):
    _backdate_check(tmpdb, 80, 1)
    _backdate_check(tmpdb, 60, 1)
    _backdate_check(tmpdb, 100, 0)
    series = {d["date"]: d["score"] for d in daily_scores(tmpdb, 7)}
    assert len(series) == 2
    assert series[sorted(series)[0]] == 70.0
    assert series[sorted(series)[1]] == 100.0


def test_business_score_averages_daily_averages(tmpdb):
    _backdate_check(tmpdb, 80, 2)
    _backdate_check(tmpdb, 60, 2)   # day-2 avg = 70
    _backdate_check(tmpdb, 90, 1)   # day-1 avg = 90
    assert business_score(tmpdb, 7) == 80  # (70+90)/2


def test_no_data_returns_none(tmpdb):
    assert business_score(tmpdb, 7) is None
    assert daily_scores(tmpdb, 7) == []


def test_scores_bounded_0_to_100(tmpdb):
    _backdate_check(tmpdb, 0, 0)
    _backdate_check(tmpdb, 100, 0)
    s = business_score(tmpdb, 7)
    assert 0 <= s <= 100
