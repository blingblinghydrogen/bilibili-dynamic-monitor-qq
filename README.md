# Bilibili Dynamic Monitor (QQ Bot Push)

自动采集 B 站（bilibili）关注 UP 主的近 4 小时新增动态，并通过 QQ Bot API 推送到手机 QQ。

<p align="center">
  <img alt="Python" src="https://img.shields.io/badge/Python-3.10%2B-blue?style=flat&logo=python">
  <img alt="Firefox" src="https://img.shields.io/badge/Browser-Firefox-FF7139?style=flat&logo=firefox">
  <img alt="License" src="https://img.shields.io/badge/License-MIT-green">
  <img alt="Platform" src="https://img.shields.io/badge/Platform-WorkBuddy-ff69b4">
</p>

---

## 功能

- 使用 Playwright + Firefox 自动登录并访问 B 站动态页
- 滚动加载无限流内容，采集所有关注 UP 主的动态
- 解析中文时间格式（x分钟前 / x小时前 / 今天HH:MM 等），筛选近 4 小时更新
- 基于 BV 号 + 内容 hash 双重去重
- 通过 QQ Bot API 将动态摘要推送到你的手机 QQ
- 首次登录后自动保存登录态，后续无需重复扫码

## 文件结构

```
bilibili-dynamic-monitor-qq/
├── README.md                                # 本文档
├── SKILL.md                                 # WorkBuddy 技能定义
├── .gitignore
├── assets/
│   └── config.example.json                  # 配置文件模板
├── references/
│   └── bilibili_dynamic_selectors.md        # B站 DOM 选择器参考（改版时用于排查）
└── scripts/
    ├── monitor.py                           # 主脚本：采集 + QQ 推送
    └── capture_openid.py                    # 一次性工具：捕获 QQ Bot OpenID
```

## 使用方法

### 1. 环境准备

```bash
# 安装 Python 依赖
pip install playwright
playwright install firefox
```

### 2. 配置 QQ Bot 凭据

将 `assets/config.example.json` 复制为 `scripts/config.json`：

```bash
cp assets/config.example.json scripts/config.json
```

编辑 `scripts/config.json`，填入你的 QQ Bot 信息：

```json
{
  "hours_back": 4,
  "headless": false,
  "max_scroll_attempts": 10,
  "scroll_wait_ms": 1500,
  "qq_app_id": "在这里填入你的QQ Bot AppID",
  "qq_app_secret": "在这里填入你的QQ Bot AppSecret"
}
```

> `qq_app_id` 和 `qq_app_secret` **必须填写**，否则推送会失败。这些信息在 QQ 开放平台（q.qq.com）创建机器人后可以获得。

### 3. 捕获 OpenID（仅首次）

QQ Bot API 发送单聊消息需要接收方的 OpenID。首次使用需要运行捕获工具：

```bash
# 重要：先关闭 WorkBuddy（QQ 每个机器人只允许一个 WebSocket 连接）
python scripts/capture_openid.py
```

按提示在 QQ 上给你的机器人发一条消息，脚本会自动捕获并保存 OpenID。

### 4. 运行监控

```bash
python scripts/monitor.py
```

运行流程：

1. 启动 Firefox，自动加载 B 站登录态
2. 首次登录需扫码，后续自动复用
3. 打开 B 站动态页，滚动加载内容
4. 解析并筛选近 4 小时动态
5. 通过 QQ Bot API 推送到手机

### 5. 定时监控（可选）

在 WorkBuddy 中创建自动化任务，设置 rrule 为 `FREQ=HOURLY;INTERVAL=4`，prompt 填写 `运行 B站动态QQ推送`。

## 配置参数说明

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `hours_back` | `4` | 回溯小时数 |
| `headless` | `false` | 是否无头模式（设为 true 则看不见 Firefox 窗口） |
| `max_scroll_attempts` | `10` | 最大滚动加载次数 |
| `scroll_wait_ms` | `1500` | 每次滚动后等待时间（毫秒） |
| `qq_app_id` | — | **必填**。QQ 开放平台的 AppID |
| `qq_app_secret` | — | **必填**。QQ 开放平台的 AppSecret |

## 前期准备（QQ Bot）

1. 在 [QQ 开放平台](https://q.qq.com) 注册并创建机器人（审核 1-3 工作日）
2. 获取 AppID 和 AppSecret
3. 可选：在 WorkBuddy 的 Claw 设置中配置机器人（用于测试连通性）
4. 记下你的 QQ 号，捕获 OpenID 时会用到

## 已知问题

| 问题 | 状态 | 说明 |
|------|------|------|
| GBK 编码崩溃 | 已修复 | Windows 控制台遇到 emoji 会崩溃，已通过 UTF-8 重编码解决 |
| 登录检测误判 | 已修复 | B站允许游客访问动态页，改为检测 SESSDATA cookie |
| 去重失效 | 已修复 | B站卡片无 data-did 属性，改为 BV号+内容 hash |
| 时间解析 | 已修复 | 时间文本含 "· 投稿了视频" 后缀，增加了分割逻辑 |

## License

MIT
