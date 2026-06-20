"""
brain/agent.py —— 业务编排层(大脑的调度中枢)

UI 和定时器都只调用这里的方法,不直接碰 prompts/llm/db。
职责:组织上下文 → 调大模型 → 落库 → 返回可展示的结果。
"""

import json
from datetime import date, timedelta

from brain import prompts
from brain.llm import chat


def build_pending_task_reminder(tasks, cfg, *, context_label="今日") -> str:
    """逐项点名未完成任务，并按当前人格给出行动压力。"""
    titles = [
        str(task["title"]).strip()
        for task in tasks
        if str(task["title"]).strip()
    ]
    if not titles:
        return ""

    task_text = "、".join(f"《{title}》" for title in titles)
    first_task = f"《{titles[0]}》"
    if cfg.persona_choice == "严师":
        return (
            f"{context_label}未完成的任务是：{task_text}。"
            f"现在就从{first_task}开始，继续拖延只会让截止日更近、明天负担更重。"
        )
    if cfg.persona_choice == "毒舌挚友":
        return (
            f"{context_label}你还有{task_text}没有完成。"
            f"怎么还不去做{first_task}？你又要偷懒了吗？"
            "再拖下去，欠下的任务只会全堆到明天。"
        )
    return (
        f"{context_label}还没有完成的是：{task_text}。"
        f"先去做{first_task}吧，别再拖啦，不然明天只会更辛苦。"
    )


def greet(db, cfg, slot: str | None = None) -> str:
    """按时段生成问候语。"""
    slot = slot or prompts.current_slot()
    tasks = db.get_today_tasks()
    return chat(prompts.greeting_prompt(slot, tasks, cfg), temperature=0.8)


def analyze_today_tasks(tasks: list[str], cfg, *, chat_fn=None) -> str:
    """分析刚录入的今日任务，返回可直接放进完整气泡的建议。"""
    clean_tasks = [str(task).strip() for task in tasks if str(task).strip()]
    if not clean_tasks:
        return ""
    chat_fn = chat_fn or chat
    return chat_fn(
        prompts.task_plan_prompt(clean_tasks, cfg),
        temperature=0.35,
    ).strip()


def generate_task_advisor_plan(db, cfg, *, chat_fn=None) -> dict:
    """生成可编辑的任务草案；不直接写入数据库。"""
    chat_fn = chat_fn or chat
    pending = [dict(row) for row in db.get_tasks("pending")]
    recent = [dict(row) for row in db.get_recent_logs(7)]
    raw = chat_fn(
        prompts.task_advisor_prompt(pending, recent, cfg),
        temperature=0.3,
        json_mode=True,
    )
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return {"analysis": str(raw).strip(), "tasks": []}
    if not isinstance(data, dict):
        return {"analysis": str(raw).strip(), "tasks": []}
    analysis = str(data.get("analysis") or "").strip()
    tasks = data.get("tasks")
    if not isinstance(tasks, list):
        tasks = []
    tasks = [
        task.strip()
        for task in tasks
        if isinstance(task, str) and task.strip()
    ][:8]
    return {"analysis": analysis, "tasks": tasks}


def _normalize_review_result(raw: str) -> dict:
    """把不可信的模型输出收敛为 UI 和数据库可安全使用的固定结构。"""
    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return {"comment": str(raw), "plan": []}

    if not isinstance(parsed, dict):
        return {"comment": str(raw), "plan": []}

    comment = parsed.get("comment", "")
    plan = parsed.get("plan", [])
    if not isinstance(comment, str):
        comment = str(comment)
    if not isinstance(plan, list):
        plan = []
    plan = [item.strip() for item in plan if isinstance(item, str) and item.strip()]
    return {"comment": comment.strip(), "plan": plan[:5]}


def prepare_evening_review(db, review_date=None) -> list[dict]:
    """返回适合 CLI/GUI 展示的今日复盘任务，不暴露 sqlite Row。"""
    return [
        {
            "task_id": row["id"],
            "title": row["title"],
            "source": row["source"],
            "scheduled_date": row["scheduled_date"],
            "due_date": row["due_date"],
            "priority": row["priority"],
            "status": row["status"],
        }
        for row in db.get_tasks_for_review(review_date)
    ]


def get_accountability_context(db) -> dict:
    """首页与复盘页共用的习惯状态，不依赖 LLM。"""
    return {
        "streak": db.get_review_streak(),
        "yesterday_plan": db.get_yesterday_plan(),
    }


def save_review_inputs(db, task_results: list[dict], summary: str,
                       reflection: str = "", mood: str = "",
                       review_date=None) -> None:
    """
    持久化用户在复盘界面确认的事实。

    这一步与 LLM 调用分离：即使网络失败，任务状态、原因和手写总结也不会丢。
    """
    for item in task_results:
        task_id = int(item["task_id"])
        status = item["status"]
        reason = (item.get("reason") or "").strip()
        current = db.get_task(task_id)
        if current is None:
            raise ValueError(f"任务 {task_id} 不存在")
        if status == "done" and current["status"] != "done":
            db.complete_task(task_id)
        elif status == "dropped" and current["status"] != "dropped":
            db.drop_task(task_id)
        elif status == "pending" and current["status"] != "pending":
            raise ValueError("已完成或已放弃的任务不能在复盘中直接恢复为未完成")
        elif status not in {"pending", "done", "dropped"}:
            raise ValueError(f"不支持的任务状态: {status}")
        db.save_task_review(
            task_id, status, reason=reason, review_date=review_date
        )

    db.save_daily_log(
        summary=summary.strip(),
        reflection=reflection.strip(),
        mood=mood.strip(),
        log_date=review_date,
    )


def generate_review_analysis(db, cfg, task_results: list[dict],
                             summary: str, reflection: str = "", mood: str = "",
                             *, review_date=None, chat_fn=None) -> dict:
    """基于已经保存的复盘事实生成点评与明日规划，并写回当天日志。"""
    chat_fn = chat_fn or chat
    recent = db.get_recent_logs(7)
    current_date = (
        date.fromisoformat(review_date) if review_date else date.today()
    )
    yest = (current_date - timedelta(days=1)).isoformat()
    ylog = db.get_daily_log(yest)
    yesterday_plan = ylog["plan_next"] if ylog else None

    msgs = prompts.review_prompt(
        task_results,
        summary,
        reflection,
        mood,
        recent,
        yesterday_plan,
        cfg,
    )
    raw = chat_fn(msgs, temperature=0.4, json_mode=True)
    data = _normalize_review_result(raw)
    plan_text = "\n".join(f"- {p}" for p in data["plan"])
    db.save_daily_log(plan_next=plan_text, log_date=review_date)
    return data


def run_evening_review(db, cfg, *, input_fn=None, output_fn=None,
                       chat_fn=None) -> dict:
    """
    晚间复盘 → 分析规划闭环(命令行交互版)。
    返回 {"comment": 点评, "plan": [明日规划...]}。
    """
    input_fn = input_fn or input
    output_fn = output_fn or print
    chat_fn = chat_fn or chat

    # 1) 逐项确认今日任务。这里使用复盘查询，包含白天已经完成/放弃的任务。
    tasks = prepare_evening_review(db)
    task_results = []
    if tasks:
        output_fn("\n—— 先逐项确认今天的任务 ——")
        for t in tasks:
            status = t["status"]
            reason = ""
            if status == "pending":
                answer = input_fn(
                    f"「{t['title']}」今天完成了吗?(y=完成/n=未完成/d=放弃) "
                ).strip().lower()
                if answer == "y":
                    status = "done"
                elif answer == "d":
                    status = "dropped"
                    reason = input_fn("  为什么决定放弃?(可回车跳过) ").strip()
                else:
                    status = "pending"
                    reason = input_fn("  没完成,原因?(可回车跳过) ").strip()
            elif status == "dropped":
                reason = "今天已标记放弃"

            task_results.append(
                {
                    "task_id": t["task_id"],
                    "title": t["title"],
                    "status": status,
                    "done": status == "done",
                    "reason": reason,
                }
            )

    # 2) 总结与反思始终是同一份记录。
    output_fn("\n—— 写下今天的总结与反思 ——")
    summary = input_fn("完成了什么、哪里没做好、明天怎样改进? ").strip()
    save_review_inputs(db, task_results, summary)
    return generate_review_analysis(
        db,
        cfg,
        task_results,
        summary,
        chat_fn=chat_fn,
    )
