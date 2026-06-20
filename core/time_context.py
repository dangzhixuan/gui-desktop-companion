"""把当前时间转换为自然的问候语境。"""

from dataclasses import dataclass
from datetime import date, datetime, timedelta


@dataclass(frozen=True)
class TimeContext:
    slot: str
    label: str
    instruction: str


def get_business_date(now: datetime | None = None) -> date:
    """凌晨 5 点前仍归入前一天，避免深夜时过早翻到新的一天。"""
    current = now or datetime.now()
    if current.hour < 5:
        return current.date() - timedelta(days=1)
    return current.date()


def get_time_context(now: datetime | None = None) -> TimeContext:
    hour = (now or datetime.now()).hour
    if hour < 5:
        return TimeContext(
            "late_night",
            "夜深了",
            "现在是深夜，可以关心对方还没休息，但不要使用早安或午安。",
        )
    if hour < 11:
        return TimeContext(
            "morning",
            "早上好",
            "现在是早晨，使用自然的早安问候，鼓励对方开始今天。",
        )
    if hour < 14:
        return TimeContext(
            "noon",
            "中午好",
            "现在是中午，轻松关心上午进度，不要说晚安。",
        )
    if hour < 18:
        return TimeContext(
            "afternoon",
            "下午好",
            "现在是下午，简短关心当前进度，不要说早安或晚安。",
        )
    if hour < 22:
        return TimeContext(
            "evening",
            "晚上好",
            "现在是傍晚或晚上，使用“晚上好”之类的问候，不要说晚安、好梦或催人睡觉。",
        )
    return TimeContext(
        "bedtime",
        "晚安",
        "现在已接近休息时间，可以温和收尾并说晚安，但只说一句。",
    )
