# 第二阶段：PySide6 GUI MVP

这一阶段把数据层和 AI 编排层接成一个可以每天使用的 Windows 桌面应用。

## 启动

```powershell
.\venv\Scripts\python.exe app.py
```

若需要个性化 AI 问候和复盘点评，先在当前 PowerShell 设置：

```powershell
$env:DEEPSEEK_API_KEY = "你的新密钥"
.\venv\Scripts\python.exe app.py
```

没有 API Key 时，任务管理、手写复盘、历史和设置仍然可用。

## 界面结构

- 今日任务：添加任务、查看全部状态、完成或放弃任务。
- 晚间复盘：逐项确认状态，记录原因、总结、反思和心情。
- 历史：按日期查看任务复盘和每日记录。
- 设置：切换人格、称呼和各时段时间。

MVP 使用单一主窗口，是为了先验证完整工作流。托盘、透明小窗和 Live2D 属于后续
表现层，不应该阻塞核心闭环验证。

## 分层

`ui/` 只负责输入和展示；它不拼 Prompt，也不直接写 SQL。

```text
PySide6 UI
    ↓
brain.agent（业务用例）
    ↓
core.db / brain.llm
```

`prepare_evening_review()` 为界面准备数据；
`save_review_inputs()` 保存确定性事实；
`generate_review_analysis()` 调用 LLM 并保存明日规划。

这种拆分使 CLI 和 GUI 可以复用同一业务逻辑，也方便未来接入托盘窗口或 Live2D。

## 为什么先保存，再调用 AI

AI 请求可能超时、断网、余额不足或输出格式错误。如果保存动作依赖 AI 成功，用户
写了十分钟的复盘可能全部丢失。

因此流程是：

```text
用户提交
  → SQLite 保存任务状态和手写内容
  → 后台线程请求 LLM
  → 成功：写回点评和明日规划
  → 失败：保留手写记录并提示稍后重试
```

这是 AI 产品常见的渐进增强设计：传统软件能力始终可用，AI 提供额外价值。

## 为什么使用后台线程

网络请求如果在 Qt 主线程运行，窗口会停止响应。`FunctionWorker` 在 `QThread`
中调用 LLM，通过 Signal 把结果送回主线程。工作线程会创建自己的 SQLite 连接，
不跨线程共享 connection。

## 设置保存

GUI 保存配置时先写入临时文件，再通过 `replace()` 原子替换正式配置。这样即使写入
过程中崩溃，也尽量避免留下半份 TOML。

API Key 永远不通过设置页写入配置文件。

## 测试

```powershell
.\venv\Scripts\python.exe -m unittest discover -s tests -v
```

GUI 测试使用 Qt 的 `offscreen` 平台，无需真的弹出窗口，验证任务表单和复盘任务
加载等关键交互。
