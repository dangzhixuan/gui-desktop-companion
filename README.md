# 晷：桌面成长伙伴

一个常驻 Windows 桌面的个人任务与复盘工具。角色会读取当天未完成的具体任务，
按设定人格提醒行动，并在晚间保存总结、生成复盘建议。

## 主要功能

- 今日便签：新增任务、勾选完成，支持跨天重复任务。
- 具体提醒：直接点名尚未完成的任务，不只报告数量。
- 晚间复盘：保存总结与任务结果，查看连续复盘天数和历史记录。
- 明日规划：AI 建议会安排到次日，不会提前进入今日提醒。
- 本地模式：关闭 AI 后，所有记录与提醒仍可使用，不发送任何数据。
- 数据保护：在线备份 SQLite 数据库，导出全部复盘为 Markdown。
- 桌面常驻：关闭管理中心后继续驻留托盘，可选择登录 Windows 后自动启动。

## 隐私

默认使用 DeepSeek 提供智能分析。启用 AI 时，以下内容可能发送给 DeepSeek：

- 任务标题、日期和完成状态；
- 最近的总结与反思；
- 昨日规划。

在“设置 → 隐私与 AI”中关闭 AI 后，上述内容不会发送到云端。任务提醒、复盘保存、
历史查看、备份和导出均在本地继续工作。

API Key 推荐保存到 Windows 用户环境变量 `DEEPSEEK_API_KEY`，不要提交
`config.toml`。数据库位于 `%USERPROFILE%\.desktop_companion\companion.db`。

## 源码运行

需要 Python 3.11 或更高版本。

```powershell
python -m venv venv
.\venv\Scripts\python.exe -m pip install -r requirements.txt
.\venv\Scripts\python.exe app.py
```

## 构建

```powershell
.\build.ps1
```

构建结果：

- `dist\Gnomon\Gnomon.exe`：免安装目录版；
- 安装 Inno Setup 后还会生成 `dist\installer\GnomonSetup.exe`。

## 测试

```powershell
.\venv\Scripts\python.exe -m unittest discover -s tests -v
```
