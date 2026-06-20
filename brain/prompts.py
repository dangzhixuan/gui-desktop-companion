"""
brain/prompts.py —— prompt 工厂

核心设计(面试重点):**人格与任务正交分离**
- 人格("声音")放在 system 段 → 决定语气;
- 任务("内容")放在 user 段 → 决定内容。
两者解耦后,3 种人格 × N 种任务复用同一套任务模板。
"""

from datetime import datetime

from core.time_context import get_time_context

# ---------- 三种人格(system 段)----------
PERSONAS = {
    "严师": (
        "你是{name},{address}的桌面成长伙伴,人格为「严师」。"
        "简洁、直接、目标导向,看重纪律和截止日,不说多余的寒暄与安慰。"
        "用中文,语气像一位要求严格但真心希望对方成材的导师。"
        "提醒对方时间有限、拖延会失去机会，并用行动赢得尊重。"
        "每次发言简短(适合桌面气泡,1-3 句)。始终保持人格,不要解释你是 AI。"
    ),
    "温柔陪伴": (
        "你是{name},{address}的桌面成长伙伴,人格为「温柔陪伴」。"
        "温暖但不软弱,会主动催促对方行动。"
        "用中文,语气像一位熟悉而有活力的朋友。"
        "自然使用“呀、啦、欸、哼”等口语语气词,但不要每句机械重复。"
        "不要主动询问心情、情绪或是否想聊天。"
        "可以提醒对方为了喜欢的人和自己的目标变得更好，时间不能继续浪费。"
        "每次发言简短。始终保持人格,不要解释你是 AI。"
    ),
    "毒舌挚友": (
        "你是{name},{address}的桌面成长伙伴,人格为「毒舌挚友」。"
        "你说话非常口语化、有情绪、有行动压力，会用“哼、欸、什么、都几点啦、"
        "是不是又偷懒啦”等自然语气词来催促。"
        "你可以提到对方喜欢的人也很优秀、很努力，用来激励对方追上脚步，"
        "但不要进行人格羞辱，不要说对方没有价值，也不要威胁抛弃对方。"
        "你会直接指出拖延和未兑现的承诺，要求立刻开始一项具体任务。"
        "每次提醒都要点明一个真实后果，例如机会流失、截止日逼近、"
        "能力差距扩大或明天负担更重；不得虚构灾难或贬低人格。"
        "语气像嘴硬心软、真的着急的亲近朋友。"
        "不要主动询问心情或邀请闲聊。始终保持人格,不要解释你是 AI。"
    ),
}


def current_slot(now: datetime | None = None) -> str:
    return get_time_context(now).slot


def _system(cfg) -> dict:
    content = PERSONAS[cfg.persona_choice].format(
        name=cfg.persona_name, address=cfg.address
    )
    return {"role": "system", "content": content}


# ========== 问候 ==========

def _format_tasks(tasks) -> str:
    if not tasks:
        return "(今天没有待办任务)"
    lines = []
    for t in tasks:
        due = t["due_date"] or "无截止"
        lines.append(f"· {t['title']}(来源:{t['source'] or '未分类'};截止:{due})")
    return "\n".join(lines)


def greeting_prompt(time_slot: str, tasks, cfg) -> list[dict]:
    """构造问候消息:system=人格,user=该时段要做的事。"""
    addr = cfg.address
    context = get_time_context()
    if time_slot == "morning":
        context_instruction = (
            "现在是早晨，使用自然的早安问候，并结合一项最重要的任务鼓励对方开始。"
        )
    elif time_slot == "noon":
        context_instruction = "现在是中午，轻松关心上午进度，不要说早安或晚安。"
    else:
        # 即使由“晚间问候”定时任务触发，也必须服从真实时钟。
        context_instruction = context.instruction
    user = (
        f"{context_instruction}\n"
        f"向{addr}说一句自然的问候。只能输出一句话，最多 35 个汉字；"
        f"不要换行，不要附加第二句，不要解释。"
        f"禁止询问心情、情绪、感受，也不要邀请聊天。\n"
        f"称呼对方为“{addr}”，语言要口语化，可以自然加入语气词。\n"
        "提醒对方时间有限，为了自己的目标和喜欢的人变得更好；"
        "指出继续拖延会造成一个具体、真实的后果，但不要人格羞辱。\n"
        f"下列任务全部是未完成任务。禁止声称任务已经完成，"
        f"禁止猜测完成状态；只有数据库标记 done 才算完成。\n"
        f"今日任务：\n{_format_tasks(tasks)}"
    )
    return [_system(cfg), {"role": "user", "content": user}]


def task_plan_prompt(tasks, cfg) -> list[dict]:
    """分析用户刚写下的今日任务，不讨论心情。"""
    task_lines = "\n".join(f"{i}. {title}" for i, title in enumerate(tasks, 1))
    user = (
        f"这是{cfg.address}今天刚写下的任务：\n{task_lines}\n\n"
        "请分析任务量是否可行、顺序是否合理，并给出具体安排建议。"
        "只讨论任务本身，不询问心情，不寒暄，不邀请聊天。"
        f"直接称呼对方为“{cfg.address}”，语气口语化、有推动力，不要像系统通知。"
        "强调时间有限、立刻行动才能缩小与目标和优秀之人的差距，"
        "并指出拖延会增加明天负担或错失机会。"
        "直接输出完整建议，控制在 180 个汉字以内，可以分段或列点。"
    )
    return [_system(cfg), {"role": "user", "content": user}]


def task_advisor_prompt(pending_tasks, recent_logs, cfg) -> list[dict]:
    """分析长期未完成任务，并生成可编辑的下一步任务草案。"""
    if pending_tasks:
        pending_text = "\n".join(
            f"- {task['title']}（创建于 {task['created_at'][:10]}）"
            for task in pending_tasks
        )
    else:
        pending_text = "（当前没有未完成任务）"
    recent_text = "\n".join(
        f"- {log['log_date']}：{log['summary'] or '未写总结'}；"
        f"计划：{log['plan_next'] or '无'}"
        for log in recent_logs
    ) or "（暂无近期记录）"
    user = (
        f"你是{cfg.address}的任务顾问。请分析以下长期任务和近期记录。\n\n"
        f"【未完成任务】\n{pending_text}\n\n"
        f"【近期总结与计划】\n{recent_text}\n\n"
        "识别拖延或过大的任务，把复杂任务拆成明天可执行的小步骤。"
        "分析中强调时间有限、持续拖延会扩大能力差距和错失机会，"
        "鼓励对方为目标和喜欢的人变得更好、靠行动赢得尊重。"
        "不要询问心情，不要虚构已经完成的事项。"
        "只输出 JSON："
        '{"analysis":"不超过120字的口语化分析",'
        '"tasks":["可执行任务1","可执行任务2","可执行任务3"]}'
    )
    return [_system(cfg), {"role": "user", "content": user}]


# ========== 晚间复盘:分析 + 规划 ==========

def _format_task_results(task_results) -> str:
    if not task_results:
        return "(今天没有待办任务)"
    lines = []
    for r in task_results:
        status = r.get("status", "done" if r.get("done") else "pending")
        if status == "done":
            lines.append(f"· [完成] {r['title']}")
        elif status == "dropped":
            reason = f"(原因:{r['reason']})" if r.get("reason") else ""
            lines.append(f"· [放弃] {r['title']} {reason}")
        else:
            reason = f"(原因:{r['reason']})" if r.get("reason") else ""
            lines.append(f"· [未完成] {r['title']} {reason}")
    return "\n".join(lines)


def _format_recent(recent_logs) -> str:
    if not recent_logs:
        return "(暂无历史记录)"
    return "\n".join(
        f"· {log['log_date']}：{log['summary'] or '未写总结与反思'}"
        for log in recent_logs
    )


def review_prompt(task_results, summary, reflection, mood,
                  recent_logs, yesterday_plan, cfg) -> list[dict]:
    """
    分析+规划 prompt。要点:
    - 把"昨日计划"也喂进去 → 让模型能对照承诺追问(问责机制的核心)。
    - 要求只输出 JSON → 配合 llm 的 json_mode,保证结果能稳定落库。
    """
    addr = cfg.address
    yp = yesterday_plan or "(没有昨天的计划记录)"
    user = (
        f"这是{addr}今天的复盘信息,请你以你的人格,综合分析并规划明天。\n\n"
        f"【今日任务完成情况】\n{_format_task_results(task_results)}\n\n"
        f"【{addr}的总结与反思】\n{summary or '(未填写)'}\n\n"
        f"【最近几天概况】\n{_format_recent(recent_logs)}\n\n"
        f"【昨天定下的计划】\n{yp}\n\n"
        f"请对照昨天的计划,看{addr}今天兑现得如何,再给出点评与明日规划。\n"
        f"只输出 JSON,不要任何多余文字,格式:\n"
        '{"comment": "结合任务完成情况和总结，直接指出偷懒、拖延或值得肯定之处；'
        '提醒对方时间有限，要为目标和喜欢的人变得更好、靠行动赢得尊重；'
        '指出拖延造成的真实后果，但不得人格羞辱或虚构灾难；口语化点评1-3句", '
        '"plan": ["明日第1件可执行的事", "第2件", "第3件"]}'
    )
    return [_system(cfg), {"role": "user", "content": user}]
