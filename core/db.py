"""
core/db.py —— 数据层（骨）

负责存储和读取：任务、每日总结/反思。
这是整个桌面伴侣的脊柱，先把它跑通再做大脑和形象。

设计原则：
- 只用标准库 sqlite3，零额外依赖，永远跑得起来。
- 所有时间用 ISO 字符串存（YYYY-MM-DD / 完整时间戳），方便排序和比较。
- DB 类把 SQL 全部封装起来，上层（agent / ui）只调用方法，不碰 SQL。
"""

import sqlite3
from datetime import datetime, date, timedelta
from pathlib import Path

# 数据库文件放在用户目录下，跟着人走，不随项目文件夹乱跑
DB_PATH = Path.home() / ".desktop_companion" / "companion.db"
SCHEMA_VERSION = 3


def _now() -> str:
    """当前时间戳，精确到秒。"""
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _today() -> str:
    """今天的日期字符串 YYYY-MM-DD。"""
    return date.today().isoformat()


class DB:
    def __init__(self, db_path: Path = DB_PATH):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        # 保持 SQLite 默认的线程检查：一个 DB 实例只属于创建它的线程。
        # 未来 UI 线程和调度线程各建自己的 DB 实例，避免共享连接造成并发问题。
        self.conn = sqlite3.connect(self.db_path, timeout=10)
        self.conn.row_factory = sqlite3.Row  # 让查询结果能用列名访问
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.execute("PRAGMA journal_mode = WAL")
        self._migrate_schema()

    def _migrate_schema(self) -> None:
        """
        把任意旧版本数据库逐步升级到最新版。

        PRAGMA user_version 是 SQLite 留给应用保存 schema 版本号的位置。
        每次迁移都放在事务中：要么完整成功，要么完整回滚。
        """
        current = self.conn.execute("PRAGMA user_version").fetchone()[0]
        if current > SCHEMA_VERSION:
            raise RuntimeError(
                f"数据库版本 {current} 高于程序支持的 {SCHEMA_VERSION}，请升级程序。"
            )

        with self.conn:
            # v1：项目最初的数据模型。即使旧库没有写版本号，也可安全补建。
            if current < 1:
                self._create_base_schema()
                self.conn.execute("PRAGMA user_version = 1")
                current = 1

            # v2：补充放弃时间，并持久化每日逐项复盘结果。
            if current < 2:
                task_columns = {
                    row["name"]
                    for row in self.conn.execute("PRAGMA table_info(tasks)").fetchall()
                }
                if "dropped_at" not in task_columns:
                    self.conn.execute("ALTER TABLE tasks ADD COLUMN dropped_at TEXT")

                self.conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS task_reviews (
                        id          INTEGER PRIMARY KEY AUTOINCREMENT,
                        review_date TEXT NOT NULL,
                        task_id     INTEGER NOT NULL,
                        status      TEXT NOT NULL
                                    CHECK(status IN ('done', 'pending', 'dropped')),
                        reason      TEXT,
                        reviewed_at TEXT NOT NULL,
                        UNIQUE(review_date, task_id),
                        FOREIGN KEY(task_id) REFERENCES tasks(id)
                    )
                    """
                )
                self.conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_task_reviews_date "
                    "ON task_reviews(review_date)"
                )
                self.conn.execute("PRAGMA user_version = 2")
                current = 2

            # v3：区分“计划哪天做”和“截止日期”，让明日任务不会提前出现。
            if current < 3:
                task_columns = {
                    row["name"]
                    for row in self.conn.execute("PRAGMA table_info(tasks)").fetchall()
                }
                if "scheduled_date" not in task_columns:
                    self.conn.execute(
                        "ALTER TABLE tasks ADD COLUMN scheduled_date TEXT"
                    )
                self.conn.execute(
                    """
                    UPDATE tasks
                    SET scheduled_date = COALESCE(
                        scheduled_date,
                        due_date,
                        substr(created_at, 1, 10)
                    )
                    """
                )
                self.conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_tasks_scheduled_date "
                    "ON tasks(scheduled_date, status)"
                )
                self.conn.execute("PRAGMA user_version = 3")

    def _create_base_schema(self) -> None:
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS tasks (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                title        TEXT NOT NULL,
                detail       TEXT,
                source       TEXT,                 -- 来源：课程作业 / 文献 / 个人 ...
                scheduled_date TEXT NOT NULL,       -- 计划执行日 YYYY-MM-DD
                due_date     TEXT,                 -- 截止日 YYYY-MM-DD，可为空
                priority     INTEGER DEFAULT 0,    -- 0 普通 1 重要 2 紧急
                status       TEXT DEFAULT 'pending', -- pending / done / dropped
                created_at   TEXT NOT NULL,
                completed_at TEXT,
                dropped_at   TEXT
            )
            """
        )
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS daily_logs (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                log_date   TEXT NOT NULL UNIQUE,   -- 一天一条 YYYY-MM-DD
                summary    TEXT,                   -- 今日总结（你写的）
                reflection TEXT,                   -- 反思 / 心得（你写的）
                mood       TEXT,                   -- 今日状态，可选
                plan_next  TEXT,                   -- 明日规划（AI 生成）
                created_at TEXT NOT NULL
            )
            """
        )

    # ---------- 任务 ----------

    def add_task(
        self,
        title,
        detail=None,
        source=None,
        due_date=None,
        priority=0,
        scheduled_date=None,
    ) -> int:
        scheduled_date = scheduled_date or due_date or _today()
        cur = self.conn.execute(
            "INSERT INTO tasks "
            "(title, detail, source, scheduled_date, due_date, priority, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                title,
                detail,
                source,
                scheduled_date,
                due_date,
                priority,
                _now(),
            ),
        )
        self.conn.commit()
        return cur.lastrowid

    def get_tasks(self, status="pending") -> list[sqlite3.Row]:
        """取某状态的任务，按优先级高、截止日近排序。status=None 取全部。"""
        if status is None:
            rows = self.conn.execute(
                "SELECT * FROM tasks ORDER BY priority DESC, due_date IS NULL, due_date"
            )
        else:
            rows = self.conn.execute(
                "SELECT * FROM tasks WHERE status = ? "
                "ORDER BY priority DESC, due_date IS NULL, due_date",
                (status,),
            )
        return rows.fetchall()

    def get_task(self, task_id: int) -> sqlite3.Row | None:
        return self.conn.execute(
            "SELECT * FROM tasks WHERE id = ?", (task_id,)
        ).fetchone()

    def get_today_tasks(self, task_date=None) -> list[sqlite3.Row]:
        """取计划日不晚于指定日期、且仍未完成的任务。"""
        today = task_date or _today()
        rows = self.conn.execute(
            "SELECT * FROM tasks WHERE status = 'pending' "
            "AND scheduled_date <= ? "
            "ORDER BY priority DESC, scheduled_date, due_date IS NULL, due_date, id",
            (today,),
        )
        return rows.fetchall()

    def complete_task(self, task_id: int) -> None:
        cur = self.conn.execute(
            "UPDATE tasks SET status = 'done', completed_at = ?, dropped_at = NULL "
            "WHERE id = ?",
            (_now(), task_id),
        )
        if cur.rowcount == 0:
            raise ValueError(f"任务 {task_id} 不存在")
        self.conn.commit()

    def reopen_task(self, task_id: int) -> None:
        """撤销误标完成/放弃，恢复为未完成并清空结束时间。"""
        cur = self.conn.execute(
            "UPDATE tasks SET status = 'pending', completed_at = NULL, dropped_at = NULL "
            "WHERE id = ?",
            (task_id,),
        )
        if cur.rowcount == 0:
            raise ValueError(f"任务 {task_id} 不存在")
        self.conn.commit()

    def drop_task(self, task_id: int) -> None:
        cur = self.conn.execute(
            "UPDATE tasks SET status = 'dropped', dropped_at = ?, completed_at = NULL "
            "WHERE id = ?",
            (_now(), task_id),
        )
        if cur.rowcount == 0:
            raise ValueError(f"任务 {task_id} 不存在")
        self.conn.commit()

    def get_tasks_for_review(self, review_date=None) -> list[sqlite3.Row]:
        """
        取某一天应该复盘的任务。

        包含：
        - 当天完成或放弃的任务；
        - 截至当天仍应关注的任务（无截止日或已经到期）。

        与 get_today_tasks() 的区别是：本方法不会漏掉白天已完成/放弃的任务。
        """
        review_date = review_date or _today()
        rows = self.conn.execute(
            """
            SELECT * FROM tasks
            WHERE scheduled_date <= ?
              AND (
                    date(completed_at) = ?
                 OR date(dropped_at) = ?
                 OR (
                        (completed_at IS NULL OR date(completed_at) > ?)
                    AND (dropped_at IS NULL OR date(dropped_at) > ?)
                 )
              )
            ORDER BY priority DESC, scheduled_date, due_date IS NULL, due_date, id
            """,
            (
                review_date,
                review_date,
                review_date,
                review_date,
                review_date,
            ),
        )
        return rows.fetchall()

    def get_task_outcome_summary(self, review_date=None) -> dict:
        """按指定日期计算当时的任务结果，不使用任务当前状态猜测历史。"""
        review_date = review_date or _today()
        rows = self.conn.execute(
            """
            SELECT
                id,
                title,
                CASE
                    WHEN completed_at IS NOT NULL
                         AND date(completed_at) <= ? THEN 'done'
                    WHEN dropped_at IS NOT NULL
                         AND date(dropped_at) <= ? THEN 'dropped'
                    ELSE 'pending'
                END AS status_on_date
            FROM tasks
            WHERE scheduled_date <= ?
            ORDER BY priority DESC, scheduled_date, due_date IS NULL, due_date, id
            """,
            (
                review_date,
                review_date,
                review_date,
            ),
        ).fetchall()
        counts = {"done": 0, "pending": 0, "dropped": 0}
        for row in rows:
            counts[row["status_on_date"]] += 1
        return {
            "date": review_date,
            "total": len(rows),
            **counts,
            "pending_titles": [
                row["title"] for row in rows if row["status_on_date"] == "pending"
            ],
        }

    def save_task_review(self, task_id: int, status: str, reason=None,
                         review_date=None) -> None:
        """保存某天对某项任务的复盘快照；重复保存会更新，而不是新增重复记录。"""
        if status not in {"done", "pending", "dropped"}:
            raise ValueError(f"不支持的复盘状态: {status}")
        review_date = review_date or _today()
        self.conn.execute(
            """
            INSERT INTO task_reviews
                (review_date, task_id, status, reason, reviewed_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(review_date, task_id) DO UPDATE SET
                status = excluded.status,
                reason = COALESCE(excluded.reason, task_reviews.reason),
                reviewed_at = excluded.reviewed_at
            """,
            (review_date, task_id, status, reason or None, _now()),
        )
        self.conn.commit()

    def get_task_reviews(self, review_date=None) -> list[sqlite3.Row]:
        """读取某天的逐项复盘，并附带任务标题等信息。"""
        review_date = review_date or _today()
        return self.conn.execute(
            """
            SELECT r.*, t.title, t.source, t.due_date, t.priority
            FROM task_reviews AS r
            JOIN tasks AS t ON t.id = r.task_id
            WHERE r.review_date = ?
            ORDER BY t.priority DESC, t.due_date IS NULL, t.due_date, t.id
            """,
            (review_date,),
        ).fetchall()

    # ---------- 每日总结 ----------

    def save_daily_log(self, summary=None, reflection=None, mood=None,
                       plan_next=None, log_date=None) -> None:
        """写/更新某天的日志（同一天只有一条，重复写会合并更新非空字段）。"""
        log_date = log_date or _today()
        existing = self.get_daily_log(log_date)
        if existing is None:
            self.conn.execute(
                "INSERT INTO daily_logs (log_date, summary, reflection, mood, plan_next, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (log_date, summary, reflection, mood, plan_next, _now()),
            )
        else:
            # 只覆盖这次传进来的非空字段，其余保持原样
            self.conn.execute(
                "UPDATE daily_logs SET "
                "summary = COALESCE(?, summary), "
                "reflection = COALESCE(?, reflection), "
                "mood = COALESCE(?, mood), "
                "plan_next = COALESCE(?, plan_next) "
                "WHERE log_date = ?",
                (summary, reflection, mood, plan_next, log_date),
            )
        self.conn.commit()

    def get_daily_log(self, log_date=None) -> sqlite3.Row | None:
        log_date = log_date or _today()
        return self.conn.execute(
            "SELECT * FROM daily_logs WHERE log_date = ?", (log_date,)
        ).fetchone()

    def get_recent_logs(self, n: int = 7) -> list[sqlite3.Row]:
        """最近 n 天的日志，给大脑做'回顾+规划'用。"""
        return self.conn.execute(
            "SELECT * FROM daily_logs ORDER BY log_date DESC LIMIT ?", (n,)
        ).fetchall()

    def get_all_logs(self) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM daily_logs ORDER BY log_date DESC"
        ).fetchall()

    def backup_to(self, target_path) -> Path:
        """使用 SQLite 在线备份 API 生成一致的数据库副本。"""
        target = Path(target_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        backup_conn = sqlite3.connect(target)
        try:
            self.conn.backup(backup_conn)
        finally:
            backup_conn.close()
        return target

    def get_review_streak(self, as_of=None) -> int:
        """连续写下每日总结的天数。

        当天尚未复盘时，允许 streak 延续到昨天；这样白天打开应用不会被误判为断更。
        如果昨天也没有总结，则 streak 为 0。
        """
        as_of_date = date.fromisoformat(as_of) if isinstance(as_of, str) else (
            as_of or date.today()
        )
        rows = self.conn.execute(
            """
            SELECT log_date
            FROM daily_logs
            WHERE log_date <= ?
              AND summary IS NOT NULL
              AND trim(summary) <> ''
            ORDER BY log_date DESC
            """,
            (as_of_date.isoformat(),),
        ).fetchall()
        logged_dates = {date.fromisoformat(row["log_date"]) for row in rows}
        expected = (
            as_of_date
            if as_of_date in logged_dates
            else as_of_date - timedelta(days=1)
        )
        streak = 0
        while expected in logged_dates:
            streak += 1
            expected -= timedelta(days=1)
        return streak

    def get_yesterday_plan(self, as_of=None) -> str | None:
        """读取前一天明确写下的计划，供今天问责展示。"""
        as_of_date = date.fromisoformat(as_of) if isinstance(as_of, str) else (
            as_of or date.today()
        )
        yesterday = (as_of_date - timedelta(days=1)).isoformat()
        row = self.get_daily_log(yesterday)
        if row is None or not row["plan_next"]:
            return None
        return row["plan_next"].strip() or None

    def close(self) -> None:
        self.conn.close()


# ---------- 自测：直接 python db.py 就能验证 ----------
if __name__ == "__main__":
    db = DB(db_path=Path("./_test_companion.db"))  # 测试用临时库

    t1 = db.add_task("读完 dependency distance 那篇文献并写 200 字总结",
                     source="文献", priority=2, due_date=_today())
    t2 = db.add_task("完成计算语言学 HW4", source="课程作业", priority=1)

    print("今日任务：")
    for t in db.get_today_tasks():
        print(f"  [{t['id']}] ({t['source']}) {t['title']}  优先级={t['priority']}")

    db.complete_task(t1)
    print(f"\n完成任务 {t1} 后，剩余未完成：{len(db.get_tasks('pending'))} 条")

    db.save_daily_log(summary="读完了文献，HW4 没动",
                      reflection="下午效率低，晚上要早点开始",
                      mood="一般")
    log = db.get_daily_log()
    print(f"\n今日日志：总结={log['summary']!r}  心情={log['mood']!r}")

    db.close()
    print("\n✅ 数据层工作正常。")
