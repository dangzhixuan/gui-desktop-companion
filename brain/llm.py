"""
brain/llm.py —— 大模型抽象层

全项目调用大模型的唯一入口。换模型(如以后改用本地 Ollama)
只需改这个文件内部实现,chat() 的签名不变,上层业务一行都不用动。
DeepSeek 的接口与 OpenAI 兼容,所以直接用 openai SDK 指向 DeepSeek。
"""

from openai import OpenAI
from core.config import Config

_cfg = None
_client = None

REQUEST_TIMEOUT_SECONDS = 20.0


def _ensure():
    """懒加载:首次调用时才读配置、建客户端。"""
    global _cfg, _client
    if _client is None:
        _cfg = Config()
        if not _cfg.ai_enabled:
            raise RuntimeError("AI 功能已关闭，当前仅使用本地提醒。")
        if not _cfg.has_api_key:
            raise RuntimeError("config.toml 里的 api_key 还没填,无法调用大模型。")
        _client = OpenAI(
            api_key=_cfg.llm["api_key"],
            base_url=_cfg.llm["base_url"],
            timeout=REQUEST_TIMEOUT_SECONDS,
            max_retries=0,
        )


def chat(messages: list[dict], *, temperature: float = 0.7,
         json_mode: bool = False) -> str:
    """
    统一对话接口。
    messages: OpenAI 风格 [{"role","content"}]
    temperature: 问候/佳句用高一点(更有文采),分析规划用低一点(更稳定)
    json_mode: 需要结构化输出(如分析规划要落库)时设 True
    """
    _ensure()
    kwargs = {}
    if json_mode:
        kwargs["response_format"] = {"type": "json_object"}
    resp = _client.chat.completions.create(
        model=_cfg.llm["model"],
        messages=messages,
        temperature=temperature,
        max_tokens=800,
        extra_body={"thinking": {"type": "disabled"}},
        **kwargs,
    )
    return resp.choices[0].message.content.strip()
