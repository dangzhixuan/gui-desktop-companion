"""
core/config.py —— 配置层

作用:把 PRD 里的产品决策(各时段时间、人格选择、佳句频率、API Key)
集中放在一个 config.toml 文件里,代码各处统一从这里读,不写死。

为什么用 toml:比 JSON 可读、能写注释,适合给人手改(MVP 阶段先手改文件)。
读取用标准库 tomllib(Python 3.11+ 自带),零额外依赖。
"""

import os
import re
import sys
import tomllib
from pathlib import Path

if getattr(sys, "frozen", False):
    CONFIG_PATH = Path.home() / ".desktop_companion" / "config.toml"
else:
    CONFIG_PATH = Path(__file__).resolve().parent.parent / "config.toml"

# 三种合法人格,用于校验
VALID_PERSONAS = ("严师", "温柔陪伴", "毒舌挚友")

# 配置文件不存在时,自动生成这份带注释的默认模板
DEFAULT_CONFIG = """# 桌面成长伙伴「晷」配置文件
# 改完保存即可,无需改代码。

[persona]
choice = "温柔陪伴"   # 三选一:严师 / 温柔陪伴 / 毒舌挚友
name   = "小晷"        # 角色名字
address = "你"         # 角色对你的称呼,如 "主人""同学"

[schedule]
morning          = "08:30"   # 早安问候
noon             = "12:30"   # 午安问候
evening_greeting = "21:00"   # 晚安问候(只是收尾,不强迫写总结)
summary          = "22:00"   # 晚间总结时间(独立于晚安)
quote_interval_minutes = 90  # 佳句弹出间隔(分钟)

[llm]
enabled  = true              # 关闭后所有任务与复盘只保存在本地
provider = "deepseek"
model    = "deepseek-chat"
api_key  = ""                # 可直接填写；环境变量 DEEPSEEK_API_KEY 优先
base_url = "https://api.deepseek.com"
"""


class Config:
    def __init__(self, path: Path = CONFIG_PATH):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # 首次运行自动落地默认配置,降低上手门槛
        if not self.path.exists():
            self.path.write_text(DEFAULT_CONFIG, encoding="utf-8")
            print(f"已生成默认配置:{self.path}(记得填 api_key)")
        with open(self.path, "rb") as f:
            self._data = tomllib.load(f)
        self._validate()

    def _validate(self) -> None:
        if self.persona_choice not in VALID_PERSONAS:
            raise ValueError(
                f"人格 choice='{self.persona_choice}' 非法,只能是 {VALID_PERSONAS}"
            )
        for key in ("morning", "noon", "evening_greeting", "summary"):
            value = self.schedule.get(key, "")
            if not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", value):
                raise ValueError(f"schedule.{key}='{value}' 不是合法的 HH:MM 时间")

    # ---------- 人格 ----------
    @property
    def persona_choice(self) -> str:
        return self._data["persona"]["choice"]

    @property
    def persona_name(self) -> str:
        return self._data["persona"]["name"]

    @property
    def address(self) -> str:
        return self._data["persona"]["address"]

    # ---------- 时间 ----------
    @property
    def schedule(self) -> dict:
        return self._data["schedule"]

    # ---------- 大模型 ----------
    @property
    def llm(self) -> dict:
        # 返回副本，避免调用方意外修改原始配置。
        # 环境变量优先；未设置时允许个人单机应用从 config.toml 读取。
        data = dict(self._data["llm"])
        env_key = os.getenv("DEEPSEEK_API_KEY", "").strip()
        file_key = str(data.get("api_key", "")).strip()
        data["api_key"] = env_key or file_key
        return data

    @property
    def has_api_key(self) -> bool:
        return bool(self.llm.get("api_key", "").strip())

    @property
    def ai_enabled(self) -> bool:
        return bool(self._data.get("llm", {}).get("enabled", True))

    def save_user_settings(self, *, persona_choice: str, persona_name: str,
                           address: str, schedule: dict,
                           ai_enabled: bool | None = None) -> None:
        """保存 GUI 中可编辑的设置，并原子替换配置文件。"""
        if persona_choice not in VALID_PERSONAS:
            raise ValueError(f"人格只能是 {VALID_PERSONAS}")

        new_data = {
            "persona": {
                "choice": persona_choice,
                "name": persona_name.strip() or "小晷",
                "address": address.strip() or "你",
            },
            "schedule": {
                "morning": schedule["morning"],
                "noon": schedule["noon"],
                "evening_greeting": schedule["evening_greeting"],
                "summary": schedule["summary"],
                "quote_interval_minutes": int(
                    schedule.get(
                        "quote_interval_minutes",
                        self.schedule.get("quote_interval_minutes", 90),
                    )
                ),
            },
            "llm": {
                "enabled": (
                    self.ai_enabled if ai_enabled is None else bool(ai_enabled)
                ),
                "provider": self._data["llm"].get("provider", "deepseek"),
                "model": self._data["llm"].get("model", "deepseek-chat"),
                # 设置页不编辑密钥，但保存其他设置时保留已有文件密钥。
                "api_key": self._data["llm"].get("api_key", ""),
                "base_url": self._data["llm"].get(
                    "base_url", "https://api.deepseek.com"
                ),
            },
        }

        old_data = self._data
        self._data = new_data
        try:
            self._validate()
        except Exception:
            self._data = old_data
            raise

        text = (
            "# 桌面成长伙伴「晷」配置文件\n"
            "# API Key 可填写在下方；环境变量 DEEPSEEK_API_KEY 优先。\n\n"
            "[persona]\n"
            f'choice = "{new_data["persona"]["choice"]}"\n'
            f'name = "{_toml_string(new_data["persona"]["name"])}"\n'
            f'address = "{_toml_string(new_data["persona"]["address"])}"\n\n'
            "[schedule]\n"
            f'morning = "{new_data["schedule"]["morning"]}"\n'
            f'noon = "{new_data["schedule"]["noon"]}"\n'
            f'evening_greeting = "{new_data["schedule"]["evening_greeting"]}"\n'
            f'summary = "{new_data["schedule"]["summary"]}"\n'
            "quote_interval_minutes = "
            f'{new_data["schedule"]["quote_interval_minutes"]}\n\n'
            "[llm]\n"
            f'enabled = {str(new_data["llm"]["enabled"]).lower()}\n'
            f'provider = "{_toml_string(new_data["llm"]["provider"])}"\n'
            f'model = "{_toml_string(new_data["llm"]["model"])}"\n'
            f'api_key = "{_toml_string(new_data["llm"]["api_key"])}"\n'
            f'base_url = "{_toml_string(new_data["llm"]["base_url"])}"\n'
        )
        temp_path = self.path.with_suffix(self.path.suffix + ".tmp")
        try:
            temp_path.write_text(text, encoding="utf-8")
            temp_path.replace(self.path)
        except Exception:
            self._data = old_data
            temp_path.unlink(missing_ok=True)
            raise


def _toml_string(value: str) -> str:
    """转义 TOML 双引号字符串中的特殊字符。"""
    return str(value).replace("\\", "\\\\").replace('"', '\\"')


# ---------- 自测:直接 python config.py 验证 ----------
if __name__ == "__main__":
    cfg = Config(path=Path("./_test_config.toml"))  # 用临时文件,不动真配置

    print(f"人格:{cfg.persona_choice} | 名字:{cfg.persona_name} | 称呼:{cfg.address}")
    print(f"早安 {cfg.schedule['morning']} / 午安 {cfg.schedule['noon']} / "
          f"晚安 {cfg.schedule['evening_greeting']} / 总结 {cfg.schedule['summary']}")
    print(f"模型:{cfg.llm['model']}")
    print("API Key 已填写" if cfg.has_api_key else "⚠️  API Key 尚未填写(下一步要用)")

    Path("./_test_config.toml").unlink(missing_ok=True)  # 清理
    print("\n✅ 配置层工作正常。")
