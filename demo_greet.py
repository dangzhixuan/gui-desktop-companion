"""
demo_greet.py —— 第一条端到端链路演示

在【项目根目录】运行:  python demo_greet.py
晷会用你在 config.toml 选的人格,说出一句问候,并念出今日任务。

链路:config(人格/Key) → db(今日任务) → prompts(拼 prompt) → llm(调 DeepSeek) → 输出
"""

from datetime import date
from core.config import Config
from core.db import DB
from brain import prompts
from brain.llm import chat


def main():
    cfg = Config()
    db = DB()

    # 为了演示能看到"任务播报",库里没任务时先塞一条(已有任务可忽略)
    if not db.get_today_tasks():
        db.add_task("读完一篇文献并写 200 字总结", source="文献",
                    priority=2, due_date=date.today().isoformat())

    slot = prompts.current_slot()
    tasks = db.get_today_tasks()
    messages = prompts.greeting_prompt(slot, tasks, cfg)

    print(f"[时段:{slot} | 人格:{cfg.persona_choice} | 名字:{cfg.persona_name}]\n")
    print(chat(messages, temperature=0.8))
    db.close()


if __name__ == "__main__":
    main()
