"""账单自动抓取调度测试：23:50 CronTrigger 边界 + job 注册参数。"""

from datetime import datetime

from apscheduler.triggers.cron import CronTrigger

from app.services import scheduler as scheduler_mod


def _tz():
    return scheduler_mod._local_zone()


def test_poll_cron_fires_at_2350():
    """CronTrigger 在 23:50 触发：前一天 23:49 → 当天 23:50。"""
    trigger = CronTrigger(hour=23, minute=50, timezone=_tz())
    nxt = trigger.get_next_fire_time(None, datetime(2026, 9, 1, 23, 49, tzinfo=_tz()))
    assert nxt == datetime(2026, 9, 1, 23, 50, tzinfo=_tz())


def test_poll_cron_next_day_after_2350():
    """23:50 之后 → 次日 23:50。"""
    trigger = CronTrigger(hour=23, minute=50, timezone=_tz())
    nxt = trigger.get_next_fire_time(None, datetime(2026, 9, 1, 23, 50, 1, tzinfo=_tz()))
    assert nxt == datetime(2026, 9, 2, 23, 50, tzinfo=_tz())


def test_scheduler_registers_poll_job(monkeypatch):
    """start_scheduler 注册账单轮询 job：id/trigger/参数正确。"""
    captured = []

    class FakeScheduler:
        def __init__(self, timezone=None):
            self.timezone = timezone

        def add_job(self, fn, trigger, **kwargs):
            captured.append({"fn": fn, "trigger": trigger, **kwargs})

        def start(self):
            pass

        def shutdown(self, wait=False):
            pass

    monkeypatch.setattr(scheduler_mod, "BackgroundScheduler", FakeScheduler)
    monkeypatch.setattr(scheduler_mod, "_scheduler", None)
    scheduler_mod.start_scheduler()
    try:
        poll_jobs = [j for j in captured if j.get("id") == "daily_credit_card_statement_poll"]
        assert len(poll_jobs) == 1
        job = poll_jobs[0]
        assert job["fn"] is scheduler_mod._scheduled_credit_card_statement_poll_job
        assert isinstance(job["trigger"], CronTrigger)
        assert job["replace_existing"] is True
        assert job["max_instances"] == 1
        assert job["coalesce"] is True
        fields = {f.name: str(f) for f in job["trigger"].fields}
        assert fields["hour"] == "23"
        assert fields["minute"] == "50"
    finally:
        scheduler_mod.shutdown_scheduler()
