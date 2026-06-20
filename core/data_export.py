from pathlib import Path


STATUS_TEXT = {"pending": "未完成", "done": "已完成", "dropped": "已放弃"}


def export_reviews_markdown(db, target_path) -> Path:
    """把全部复盘记录导出为便于长期保存的 Markdown 文件。"""
    target = Path(target_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    lines = ["# 晷：复盘记录", ""]

    logs = db.get_all_logs()
    if not logs:
        lines.extend(["还没有复盘记录。", ""])

    for log in logs:
        log_date = log["log_date"]
        reviews = db.get_task_reviews(log_date)
        lines.extend([f"## {log_date}", "", "### 任务完成情况", ""])
        if reviews:
            for review in reviews:
                status = STATUS_TEXT.get(review["status"], review["status"])
                reason = (review["reason"] or "").strip()
                suffix = f"：{reason}" if reason else ""
                lines.append(f"- [{status}] {review['title']}{suffix}")
        else:
            lines.append("- 无任务记录")

        lines.extend(
            [
                "",
                "### 总结与反思",
                "",
                (log["summary"] or "无").strip(),
                "",
                "### 明日规划",
                "",
                (log["plan_next"] or "无").strip(),
                "",
                "---",
                "",
            ]
        )

    target.write_text("\n".join(lines), encoding="utf-8")
    return target
