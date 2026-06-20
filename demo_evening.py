"""
demo_evening.py —— 核心闭环演示

项目根目录运行:  python demo_evening.py
晷会逐项问你今天的任务完成情况、收集你的总结反思,
再综合"完成度 + 心得 + 昨日计划"给出点评并规划明天,最后存进数据库。

明天再跑一次,你会发现它能引用今天定下的计划来对照——这就是"问责"。
"""

from core.config import Config
from core.db import DB
from brain import agent


def main():
    cfg = Config()
    db = DB()

    result = agent.run_evening_review(db, cfg)

    print("\n========== 晷的点评 ==========")
    print(result.get("comment", "(无)"))
    print("\n========== 明日规划 ==========")
    plan = result.get("plan", [])
    if plan:
        for i, p in enumerate(plan, 1):
            print(f"{i}. {p}")
    else:
        print("(模型这次没给出规划)")

    db.close()


if __name__ == "__main__":
    main()
