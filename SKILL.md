---
name: bilibili-dynamic-monitor-qq
description: "B站（哔哩哔哩/bilibili）动态监控技能（QQ推送版）。使用 Firefox 浏览器自动打开 B 站动态页，识别近 4 小时内关注 UP 主的新增动态，并通过 WorkBuddy 的 QQ 机器人推送到手机 QQ。当用户说'B站动态QQ推送'、'bilibili动态QQ'、'QQ推送动态'、'动态通知QQ'时触发此技能。与 bilibili-dynamic-monitor（PushPlus版）功能相同，仅推送通道不同。"
agent_created: true
---

# Bilibili Dynamic Monitor (QQ Push via WorkBuddy)

## Overview

监控 B 站（bilibili）关注 UP 主的动态更新，识别近 4 小时新增内容，通过 WorkBuddy 的 QQ 机器人推送到手机 QQ。使用 Python + Playwright 驱动 Firefox 浏览器完成自动化采集。

与 `bilibili-dynamic-monitor`（PushPlus 版）功能完全相同，区别在于推送通道：本技能不调用第三方推送 API，而是将采集结果输出给 WorkBuddy agent，由 agent 通过已配置的 QQ 机器人推送到用户手机。

## Prerequisites

**必须在 WorkBuddy 中配置 QQ 机器人**（通过 Claw 功能）。配置流程：

1. QQ 账号完成实名认证
2. 在 QQ 开放平台（q.qq.com）注册并创建机器人（审核 1-3 工作日）
3. 获取 AppID & AppSecret
4. 在 WorkBuddy 设置中进入 Claw → QQ 机器人配置，填入 AppID & AppSecret
5. WorkBuddy 自动生成 Webhook 地址
6. 在 QQ 开放平台后台配置回调地址（去掉 `https://` 前缀）
7. 配置单聊权限
8. 在手机 QQ 中添加该机器人为好友

如果未配置 QQ 机器人，脚本仍可正常运行并采集动态，但结果只能在 WorkBuddy 对话界面查看，无法推送到手机 QQ。

## When to Use

触发条件（满足任一即触发）：

- 用户说"B站动态QQ推送"、"bilibili动态QQ"、"QQ推送动态"
- 用户说"动态通知QQ"、"通过QQ推送B站动态"
- 用户希望用 QQ 而非微信接收 B 站动态通知

如果用户说"B站动态"但未指定推送方式，优先使用 `bilibili-dynamic-monitor`（PushPlus 版），除非用户明确提到 QQ。

## Architecture

```
bilibili-dynamic-monitor-qq/
├── SKILL.md                              # 本文件
├── scripts/
│   └── monitor.py                        # 主脚本：采集 + 输出结果（不推送）
├── references/
│   └── bilibili_dynamic_selectors.md     # B站页面 DOM 选择器参考
└── assets/
    └── config.example.json               # 配置文件模板
```

运行时生成：
- `scripts/storage_state.json` — B 站登录态（cookie），可复用 PushPlus 版的登录态
- `scripts/config.json` — 用户配置
- `scripts/result.md` — 最新一次采集结果

**venv 复用**：本技能的 `monitor.py` 优先使用自己的 `.venv`，如果不存在则自动回退到 `bilibili-dynamic-monitor/scripts/.venv`，避免重复安装 Playwright 和 Firefox 驱动。

## Workflow

### Step 1: Run the Monitor Script

执行采集脚本，脚本会自动打开 Firefox 浏览器、加载 B 站登录态、采集动态、筛选近 N 小时、输出结果。

```bash
python "C:\Users\Administrator\.workbuddy\skills\bilibili-dynamic-monitor-qq\scripts\monitor.py"
```

脚本会自动：
1. 检查并复用 venv（自己的或 PushPlus 版的）
2. 加载 `storage_state.json`（如不存在则要求首次登录）
3. 打开 Firefox → 导航到 `https://t.bilibili.com`
4. 滚动加载动态，解析 UP 主、内容、时间
5. 筛选近 `hours_back` 小时（默认 4）的动态
6. 将结果格式化为 Markdown，输出到 stdout 和 `result.md`

### Step 2: Push via WorkBuddy QQ Bot

脚本执行完成后，**WorkBuddy agent 读取脚本输出（stdout 中 RESULT_START 与 RESULT_END 之间的内容，或 `scripts/result.md` 文件），然后通过已配置的 QQ 机器人将结果推送到用户手机 QQ**。

推送动作由 WorkBuddy agent 完成，不需要脚本调用任何推送 API。agent 应：

1. 读取 `scripts/result.md` 的内容
2. 将内容通过 QQ 机器人发送给用户
3. 如果 QQ 机器人未配置，告知用户需要在 WorkBuddy 设置中配置

### Step 3: First-Run Login (if needed)

首次运行时，脚本会启动 Firefox 并打开 B 站登录页，等待用户手动扫码登录。登录成功后保存 `storage_state.json`。

如果 PushPlus 版（`bilibili-dynamic-monitor`）已经登录过，可以将它的 `storage_state.json` 复制到本技能的 `scripts/` 目录下复用：

```bash
cp "C:\Users\Administrator\.workbuddy\skills\bilibili-dynamic-monitor\scripts\storage_state.json" \
   "C:\Users\Administrator\.workbuddy\skills\bilibili-dynamic-monitor-qq\scripts\storage_state.json"
```

### Step 4: Scheduled Monitoring (Optional)

使用 WorkBuddy 的 automation 功能设置定时任务。推荐每 4 小时运行一次：

- `scheduleType`: `recurring`
- `rrule`: `FREQ=HOURLY;INTERVAL=4`
- `prompt`: `运行 B站动态QQ推送技能，检查近 4 小时新增动态并通过 QQ 机器人推送到我手机`

## Configuration

`config.json` 字段：

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `hours_back` | int | 4 | 回溯小时数 |
| `headless` | bool | false | 是否无头模式（保持 false 以满足"打开浏览器"需求） |
| `max_scroll_attempts` | int | 10 | 最大滚动次数 |
| `scroll_wait_ms` | int | 1500 | 滚动后等待毫秒数 |

注意：与 PushPlus 版不同，本技能的 `config.json` **不需要** `pushplus_token` 和 `pushplus_url` 字段。

## Error Handling

| 问题 | 原因 | 解决方案 |
|------|------|----------|
| 首次登录后无反应 | 登录检测失败 | 手动确认已登录后按 Enter 继续 |
| QQ 未收到推送 | QQ 机器人未配置 | 在 WorkBuddy 设置 → Claw → QQ 机器人中配置 |
| 动态列表为空 | 登录态失效或未关注 UP 主 | 删除 `storage_state.json` 重新登录，或复用 PushPlus 版的登录态 |
| Firefox 未启动 | 驱动未安装 | 运行 `monitor.py --setup`，或确保 PushPlus 版的 venv 可用 |
| 时间解析错误 | B 站时间格式变更 | 参考 `references/bilibili_dynamic_selectors.md` 更新解析逻辑 |

## Key Constraints

- 浏览器固定使用 **Firefox**
- 登录态通过 Playwright 的 `storage_state` 机制持久化
- 推送通道为 **WorkBuddy QQ 机器人**（不调用第三方推送 API）
- 回溯时间窗口默认 4 小时，可通过 `config.json` 的 `hours_back` 调整
- 保持有头模式（`headless=false`）
- venv 可复用 `bilibili-dynamic-monitor` 的环境，避免重复安装
