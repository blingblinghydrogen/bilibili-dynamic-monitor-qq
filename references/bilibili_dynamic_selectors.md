# B站动态页 DOM 选择器参考

本文档记录 B 站动态页（`https://t.bilibili.com`）的关键 CSS 选择器，用于 `scripts/monitor.py` 的页面解析。B 站前端可能改版，改版后需更新此文档与脚本中的选择器。

## 页面结构概览

```
.bili-dyn-list__items               # 动态列表容器
└── .bili-dyn-list__item            # 单条动态卡片（重复）
    ├── .bili-dyn-item__main        # 动态主体
    │   ├── .bili-dyn-title         # 头部区域
    │   │   ├── .bili-dyn-avatar    # UP主头像
    │   │   └── .bili-dyn-title__text  # UP主名称
    │   ├── .bili-dyn-content       # 动态内容区
    │   │   ├── .bili-dyn-text      # 文字动态
    │   │   ├── .bili-dyn-video     # 视频动态
    │   │   └── .bili-dyn-card      # 卡片动态（图文/专栏）
    │   └── .bili-dyn-item__footer  # 底部交互区
    │       └── .bili-dyn-time      # 时间区域
    │           └── .bili-dyn-time__text  # 时间文本
    └── [data-did]                  # 动态ID（卡片属性）
```

## 核心选择器

### 动态列表容器

```python
".bili-dyn-list__items"
```

### 单条动态卡片

```python
".bili-dyn-list__item"
```

卡片上的动态 ID 属性：

```python
# 方式1: data-did 属性
card.get_attribute("data-did")

# 方式2: data-epoch 属性（部分版本）
card.get_attribute("data-epoch")
```

### UP 主名称

```python
".bili-dyn-title__text"
```

文本内容即为 UP 主昵称。

### 动态时间

```python
".bili-dyn-time__text"
```

文本内容示例：`"2小时前"`、`"30分钟前"`、`"今天 15:30"`、`"昨天 22:00"`、`"12-25"`。

### 动态内容

#### 文字动态

```python
".bili-dyn-text"
# 或更精确：
".bili-dyn-text__main"
```

#### 视频动态

```python
".bili-dyn-video"
# 视频标题：
".bili-dyn-video__title"
# 视频封面：
".bili-dyn-video__cover img"
```

#### 图文/专栏卡片

```python
".bili-dyn-card"
# 卡片标题：
".bili-dyn-card__title"
# 卡片摘要：
".bili-dyn-card__desc"
```

### 动态链接

动态卡片本身没有直接的链接元素，需从 `data-did` 构造：

```python
dynamic_id = card.get_attribute("data-did")
dynamic_url = f"https://t.bilibili.com/{dynamic_id}"
```

## 动态类型识别

通过内容区子元素判断动态类型：

```python
content = card.query_selector(".bili-dyn-content")
if content.query_selector(".bili-dyn-video"):
    dyn_type = "video"
elif content.query_selector(".bili-dyn-card"):
    dyn_type = "article"  # 专栏/图文
elif content.query_selector(".bili-dyn-text"):
    dyn_type = "text"
else:
    dyn_type = "unknown"
```

## 滚动加载

B 站动态页使用无限滚动。滚动触发加载的方式：

```python
# 方式1: 滚动到页面底部
await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")

# 方式2: 滚动动态列表容器
await page.evaluate("""
    const container = document.querySelector('.bili-dyn-list__items');
    if (container) {
        container.scrollTop = container.scrollHeight;
    }
""")

# 等待新动态加载
await page.wait_for_timeout(1500)
```

## 登录态检测

### 登录页选择器

```python
# 扫码登录二维码容器
".login-scan-box__qr-code"
# 或
".qrcode-img"

# 登录成功标志（跳转到动态页或检测用户头像）
".bili-header-avatar"  # 顶部导航栏用户头像
```

### 登录失效检测

```python
# 登录失效提示
".login-tip"
# 或检测 URL 是否跳回登录页
page.url.startswith("https://passport.bilibili.com/login")
```

## 时间格式解析规则

B 站动态时间文本的 5 种格式及解析规则：

| 文本格式 | 示例 | 含义 | 解析方式 |
|----------|------|------|----------|
| `刚刚` | 刚刚 | 0 分钟前 | `now` |
| `x分钟前` | 30分钟前 | x 分钟前 | `now - x minutes` |
| `x小时前` | 2小时前 | x 小时前 | `now - x hours` |
| `今天 HH:MM` | 今天 15:30 | 今天指定时间 | `today 15:30` |
| `昨天 HH:MM` | 昨天 22:00 | 昨天指定时间 | `yesterday 22:00` |
| `MM-DD` | 12-25 | 今年指定日期 | `current_year-MM-DD` |
| `YYYY-MM-DD` | 2025-12-25 | 指定日期 | `YYYY-MM-DD` |

正则匹配模式：

```python
import re

# 刚刚
re.match(r"^刚刚$", text)
# x分钟前
re.match(r"^(\d+)分钟前$", text)
# x小时前
re.match(r"^(\d+)小时前$", text)
# 今天 HH:MM
re.match(r"^今天\s*(\d{1,2}):(\d{2})$", text)
# 昨天 HH:MM
re.match(r"^昨天\s*(\d{1,2}):(\d{2})$", text)
# MM-DD
re.match(r"^(\d{1,2})-(\d{1,2})$", text)
# YYYY-MM-DD
re.match(r"^(\d{4})-(\d{1,2})-(\d{1,2})$", text)
```

## 改版应对策略

若脚本运行时选择器失效，按以下步骤排查：

1. **手动打开** `https://t.bilibili.com`，F12 检查元素
2. **对比当前 DOM 结构**与本文档，定位差异
3. **更新本文档**的选择器
4. **同步更新** `scripts/monitor.py` 中的选择器常量（文件顶部的 `SELECTORS` 字典）
5. **重新测试**运行

选择器在 `monitor.py` 中集中定义为常量，便于统一维护：

```python
SELECTORS = {
    "dyn_list": ".bili-dyn-list__items",
    "dyn_item": ".bili-dyn-list__item",
    "up_name": ".bili-dyn-title__text",
    "dyn_time": ".bili-dyn-time__text",
    "dyn_text": ".bili-dyn-text__main",
    "dyn_video": ".bili-dyn-video",
    "dyn_video_title": ".bili-dyn-video__title",
    "dyn_card": ".bili-dyn-card",
    "dyn_card_title": ".bili-dyn-card__title",
    "dyn_card_desc": ".bili-dyn-card__desc",
    "dyn_content": ".bili-dyn-content",
    "header_avatar": ".bili-header-avatar",
    "login_qr": ".login-scan-box__qr-code",
}
```
