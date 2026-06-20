import unittest
from datetime import datetime

from core.time_context import get_business_date, get_time_context


class TimeContextTests(unittest.TestCase):
    def test_six_pm_is_evening_not_bedtime(self):
        context = get_time_context(datetime(2026, 6, 19, 18, 0))
        self.assertEqual(context.slot, "evening")
        self.assertEqual(context.label, "晚上好")
        self.assertIn("不要说晚安", context.instruction)

    def test_bedtime_starts_at_ten_pm(self):
        context = get_time_context(datetime(2026, 6, 19, 22, 0))
        self.assertEqual(context.slot, "bedtime")
        self.assertEqual(context.label, "晚安")

    def test_after_midnight_is_previous_business_day(self):
        now = datetime(2026, 6, 20, 0, 48)

        self.assertEqual(get_time_context(now).slot, "late_night")
        self.assertEqual(get_business_date(now).isoformat(), "2026-06-19")

    def test_five_am_starts_new_business_day(self):
        now = datetime(2026, 6, 20, 5, 0)

        self.assertEqual(get_business_date(now).isoformat(), "2026-06-20")
