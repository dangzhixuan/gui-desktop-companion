import unittest

from core.scheduler import CompanionScheduler, parse_time


class FakeScheduler:
    def __init__(self):
        self.jobs = {}
        self.started = False
        self.stopped = False

    def add_job(self, func, trigger, **kwargs):
        self.jobs[kwargs["id"]] = {
            "func": func,
            "trigger": trigger,
            **kwargs,
        }

    def start(self):
        self.started = True

    def remove_job(self, job_id):
        self.jobs.pop(job_id)

    def shutdown(self, wait=False):
        self.stopped = True


class SchedulerTests(unittest.TestCase):
    def test_parse_time(self):
        self.assertEqual(parse_time("08:30"), (8, 30))
        self.assertEqual(parse_time("22:05"), (22, 5))

    def test_start_registers_only_summary_and_task_reminder(self):
        backend = FakeScheduler()
        scheduler = CompanionScheduler(
            lambda slot: None,
            lambda: None,
            lambda: None,
            scheduler=backend,
        )

        scheduler.start(
            {
                "morning": "08:30",
                "noon": "12:30",
                "evening_greeting": "21:00",
                "summary": "22:00",
            }
        )

        self.assertTrue(backend.started)
        self.assertEqual(
            set(backend.jobs),
            {
                "evening_summary",
                "task_reminder",
            },
        )
        self.assertEqual(backend.jobs["evening_summary"]["minute"], 0)

    def test_reload_replaces_jobs_instead_of_duplicating(self):
        backend = FakeScheduler()
        scheduler = CompanionScheduler(
            lambda slot: None,
            lambda: None,
            lambda: None,
            scheduler=backend,
        )
        schedule = {
            "morning": "08:30",
            "noon": "12:30",
            "evening_greeting": "21:00",
            "summary": "22:00",
        }
        scheduler.start(schedule)
        schedule["summary"] = "23:15"
        scheduler.reload(schedule)

        self.assertEqual(len(backend.jobs), 2)
        self.assertEqual(backend.jobs["evening_summary"]["hour"], 23)
        self.assertEqual(backend.jobs["evening_summary"]["minute"], 15)
        self.assertTrue(
            all(job["replace_existing"] for job in backend.jobs.values())
        )
        self.assertEqual(backend.jobs["task_reminder"]["minutes"], 90)


if __name__ == "__main__":
    unittest.main()
