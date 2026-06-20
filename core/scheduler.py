"""应用内定时调度。

调度器只负责“什么时候触发什么事件”，不直接操作 Qt 控件或数据库。
界面层通过回调接收事件，因此这部分可以独立测试。
"""

from apscheduler.schedulers.background import BackgroundScheduler


def parse_time(value: str) -> tuple[int, int]:
    """把经过 Config 校验的 HH:mm 转成 APScheduler 需要的时、分。"""
    hour, minute = value.split(":", 1)
    return int(hour), int(minute)


class CompanionScheduler:
    def __init__(
        self,
        on_greeting,
        on_summary,
        on_task_reminder=None,
        *,
        scheduler=None,
    ):
        self.on_greeting = on_greeting
        self.on_summary = on_summary
        self.on_task_reminder = on_task_reminder
        self.scheduler = scheduler or BackgroundScheduler()
        self._started = False

    def start(self, schedule: dict) -> None:
        self.reload(schedule)
        if not self._started:
            self.scheduler.start()
            self._started = True

    def reload(self, schedule: dict) -> None:
        """按最新设置重建任务；固定 id 保证重复保存设置不会叠加提醒。"""
        for job_id in ("greeting_morning", "greeting_noon", "greeting_evening_greeting"):
            try:
                self.scheduler.remove_job(job_id)
            except Exception:
                pass

        hour, minute = parse_time(schedule["summary"])
        self.scheduler.add_job(
            self.on_summary,
            "cron",
            id="evening_summary",
            hour=hour,
            minute=minute,
            replace_existing=True,
            coalesce=True,
            max_instances=1,
        )

        if self.on_task_reminder is not None:
            interval = max(15, int(schedule.get("quote_interval_minutes", 90)))
            self.scheduler.add_job(
                self.on_task_reminder,
                "interval",
                id="task_reminder",
                minutes=interval,
                replace_existing=True,
                coalesce=True,
                max_instances=1,
            )

    def shutdown(self) -> None:
        if self._started:
            self.scheduler.shutdown(wait=False)
            self._started = False
