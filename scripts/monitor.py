#!/usr/bin/env python3
"""
Bilibili Dynamic Monitor (QQ Push via WorkBuddy)
================================================
Monitor Bilibili dynamics from followed UP owners within the last N hours.
Results are output to stdout (between RESULT_START/RESULT_END markers) and
written to result.md. The WorkBuddy agent then pushes the result to the
user's phone via the WorkBuddy QQ bot.

Usage:
    python monitor.py              # Run monitoring
    python monitor.py --setup      # Install dependencies
    python monitor.py --login      # Force re-login (delete storage_state.json)
"""

import argparse
import json
import os
import re
import sys
import subprocess
import time
from datetime import datetime, timedelta
from pathlib import Path

# Fix Windows console encoding: force stdout to UTF-8 so emoji/CJK won't crash
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# ---------------------------------------------------------------------------
# Path setup
# ---------------------------------------------------------------------------
SCRIPT_DIR = Path(__file__).resolve().parent
CONFIG_PATH = SCRIPT_DIR / "config.json"
STORAGE_STATE_PATH = SCRIPT_DIR / "storage_state.json"
RESULT_PATH = SCRIPT_DIR / "result.md"
OPENID_PATH = SCRIPT_DIR / "openid.txt"
DYNAMIC_URL = "https://t.bilibili.com"
LOGIN_URL = "https://passport.bilibili.com/login"

# QQ Bot API
QQ_TOKEN_URL = "https://bots.qq.com/app/getAppAccessToken"
QQ_API_BASE = "https://api.sgroup.qq.com"

# Sibling skill (bilibili-dynamic-monitor, PushPlus version) for venv sharing
SIBLING_VENV = SCRIPT_DIR.parent.parent / "bilibili-dynamic-monitor" / "scripts" / ".venv"

# ---------------------------------------------------------------------------
# Selectors (see references/bilibili_dynamic_selectors.md)
# ---------------------------------------------------------------------------
SELECTORS = {
    "dyn_list": ".bili-dyn-list__items",
    "dyn_item": ".bili-dyn-list__item",
    "up_name": ".bili-dyn-title__text",
    "dyn_time": ".bili-dyn-time",
    "dyn_text": ".bili-dyn-text__main",
    "dyn_video_card": ".bili-dyn-card-video",
    "dyn_video_title": ".bili-dyn-card-video__title",
    "dyn_video_desc": ".bili-dyn-card-video__desc",
    "dyn_card_article": ".bili-dyn-card-article",
    "dyn_card_article_title": ".bili-dyn-card-article__title",
    "dyn_content": ".bili-dyn-content",
    "dyn_content_orig": ".bili-dyn-content__orig",
    "dyn_content_forward": ".bili-dyn-content__forward",
    "header_avatar": ".bili-header-avatar",
    "login_qr": ".login-scan-box__qr-code",
    "bili-avatar": ".bili-avatar",
}


# ---------------------------------------------------------------------------
# Dependency management
# ---------------------------------------------------------------------------
def ensure_venv():
    """Ensure an isolated venv exists in the skill's scripts dir."""
    venv_dir = SCRIPT_DIR / ".venv"
    if not venv_dir.exists():
        print("[setup] Creating isolated venv...")
        subprocess.check_call([sys.executable, "-m", "venv", str(venv_dir)])
    if os.name == "nt":
        return venv_dir / "Scripts" / "python.exe"
    return venv_dir / "bin" / "python"


def run_setup():
    """Install playwright into the venv, then install firefox."""
    venv_python = ensure_venv()
    print("[setup] Upgrading pip...")
    subprocess.check_call([str(venv_python), "-m", "pip", "install", "--upgrade", "pip"])
    print("[setup] Installing playwright...")
    subprocess.check_call([str(venv_python), "-m", "pip", "install", "playwright"])
    print("[setup] Installing Firefox browser driver...")
    subprocess.check_call([str(venv_python), "-m", "playwright", "install", "firefox"])
    print("[setup] Done. You can now run: python monitor.py")
    return venv_python


def get_venv_python():
    """Return the venv python executable path.
    Checks own .venv first, then falls back to the sibling skill's .venv
    (bilibili-dynamic-monitor) to avoid duplicate installs."""
    candidates = []
    # Own venv
    if os.name == "nt":
        candidates.append(SCRIPT_DIR / ".venv" / "Scripts" / "python.exe")
    else:
        candidates.append(SCRIPT_DIR / ".venv" / "bin" / "python")
    # Sibling skill's venv (bilibili-dynamic-monitor, PushPlus version)
    if os.name == "nt":
        candidates.append(SIBLING_VENV / "Scripts" / "python.exe")
    else:
        candidates.append(SIBLING_VENV / "bin" / "python")
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def maybe_relaunch_in_venv():
    """If running under system Python but a venv exists, re-exec in venv."""
    venv_python = get_venv_python()
    if not venv_python:
        return
    current_python = Path(sys.executable).resolve()
    if current_python == venv_python.resolve():
        return
    print(f"[boot] Re-launching in venv: {venv_python}")
    os.execv(str(venv_python), [str(venv_python)] + sys.argv)


def import_playwright():
    """Try to import playwright; if missing, offer to run --setup."""
    try:
        from playwright.sync_api import sync_playwright
        return sync_playwright
    except ImportError:
        print("[error] playwright is not installed.")
        print("[error] Run: python monitor.py --setup")
        sys.exit(1)


# ---------------------------------------------------------------------------
# Config (no pushplus fields — push is handled by WorkBuddy agent)
# ---------------------------------------------------------------------------
def load_config():
    if not CONFIG_PATH.exists():
        example = Path(__file__).resolve().parent.parent / "assets" / "config.example.json"
        if example.exists():
            import shutil
            shutil.copy(example, CONFIG_PATH)
            print(f"[config] Copied template to {CONFIG_PATH}")
        else:
            print(f"[error] Config not found: {CONFIG_PATH}")
            sys.exit(1)
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        cfg = json.load(f)
    cfg.setdefault("hours_back", 4)
    cfg.setdefault("headless", False)
    cfg.setdefault("max_scroll_attempts", 10)
    cfg.setdefault("scroll_wait_ms", 1500)
    return cfg


# ---------------------------------------------------------------------------
# Time parsing
# ---------------------------------------------------------------------------
def parse_bilibili_time(text, now):
    """Parse Bilibili's Chinese time strings into a datetime object.
    B站动态时间文本可能包含附加信息，如 '刚刚 · 投稿了视频'，需先提取时间部分。"""
    text = text.strip()
    if not text:
        return datetime.min

    # B站时间文本可能带 "·" 分隔的附加描述，只取时间部分
    # 例如: "刚刚 · 投稿了视频" → "刚刚"
    # 例如: "4小时前 · 转发动态" → "4小时前"
    if "·" in text:
        text = text.split("·")[0].strip()

    if text == "刚刚":
        return now

    m = re.match(r"^(\d+)\s*分钟前$", text)
    if m:
        return now - timedelta(minutes=int(m.group(1)))

    m = re.match(r"^(\d+)\s*小时前$", text)
    if m:
        return now - timedelta(hours=int(m.group(1)))

    m = re.match(r"^(\d+)\s*天前$", text)
    if m:
        return now - timedelta(days=int(m.group(1)))

    m = re.match(r"^今天\s*(\d{1,2}):(\d{2})$", text)
    if m:
        h, mi = int(m.group(1)), int(m.group(2))
        return now.replace(hour=h, minute=mi, second=0, microsecond=0)

    m = re.match(r"^昨天\s*(\d{1,2}):(\d{2})$", text)
    if m:
        h, mi = int(m.group(1)), int(m.group(2))
        yesterday = now - timedelta(days=1)
        return yesterday.replace(hour=h, minute=mi, second=0, microsecond=0)

    m = re.match(r"^前天\s*(\d{1,2}):(\d{2})$", text)
    if m:
        h, mi = int(m.group(1)), int(m.group(2))
        day_before = now - timedelta(days=2)
        return day_before.replace(hour=h, minute=mi, second=0, microsecond=0)

    m = re.match(r"^(\d{1,2})-(\d{1,2})$", text)
    if m:
        mo, d = int(m.group(1)), int(m.group(2))
        return now.replace(month=mo, day=d, hour=0, minute=0, second=0, microsecond=0)

    m = re.match(r"^(\d{4})-(\d{1,2})-(\d{1,2})$", text)
    if m:
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        return datetime(y, mo, d)

    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return datetime.min


# ---------------------------------------------------------------------------
# Browser & login
# ---------------------------------------------------------------------------
def wait_for_login(page, context, timeout_sec=300):
    """Wait for the user to complete login manually.
    Primary indicator: SESSDATA cookie (reliable).
    Secondary indicator: URL no longer on passport/login page."""
    print("[login] Waiting for manual login (scan QR or enter credentials)...")
    print(f"[login] Timeout: {timeout_sec} seconds")
    start = time.time()
    while time.time() - start < timeout_sec:
        # Primary check: SESSDATA cookie appears after successful login
        try:
            cookies = context.cookies()
            for c in cookies:
                if c.get("name") == "SESSDATA" and "bilibili" in c.get("domain", ""):
                    print("[login] Login confirmed (SESSDATA cookie found).")
                    return True
        except Exception:
            pass
        # Secondary check: URL left the login page
        url = page.url
        if "passport.bilibili.com" not in url and "login" not in url.lower():
            print(f"[login] Detected redirect to: {url}")
            try:
                page.wait_for_selector(SELECTORS["header_avatar"], timeout=5000)
                print("[login] Login confirmed (avatar found).")
                return True
            except Exception:
                print("[login] Login likely successful (URL changed).")
                return True
        time.sleep(2)
    print("[login] Timeout waiting for login.")
    return False


def is_logged_in(context, page):
    """Check if the user is actually logged in (not a guest)."""
    cookies = context.cookies()
    for c in cookies:
        if c.get("name") == "SESSDATA" and "bilibili" in c.get("domain", ""):
            return True
    try:
        avatar = page.query_selector(SELECTORS["header_avatar"])
        if avatar:
            return True
    except Exception:
        pass
    try:
        avatar = page.query_selector(".bili-header .bili-avatar, .header-login-entry .bili-avatar")
        if avatar:
            return True
    except Exception:
        pass
    return False


def ensure_login(context, page):
    """Ensure the user is logged in. If not, navigate to login page and wait."""
    print(f"[nav] Navigating to {DYNAMIC_URL}")
    page.goto(DYNAMIC_URL, wait_until="domcontentloaded", timeout=30000)
    page.wait_for_timeout(2000)

    if is_logged_in(context, page):
        print("[login] Already logged in.")
        context.storage_state(path=str(STORAGE_STATE_PATH))
        return True

    print("[login] Not logged in (guest access detected). Navigating to login page...")
    page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=30000)
    page.wait_for_timeout(2000)
    print("[login] Please complete login (scan QR code or enter credentials) in the browser window.")
    print("[login] The script will continue automatically once login is detected.")
    if not wait_for_login(page, context, timeout_sec=300):
        print("[login] Login failed or timed out.")
        return False

    page.goto(DYNAMIC_URL, wait_until="domcontentloaded", timeout=30000)
    page.wait_for_timeout(2000)

    if not is_logged_in(context, page):
        print("[login] Login verification failed. Please try again with --login flag.")
        return False

    context.storage_state(path=str(STORAGE_STATE_PATH))
    print(f"[login] Login confirmed. Saved state to {STORAGE_STATE_PATH}")
    return True


# ---------------------------------------------------------------------------
# Dynamic collection
# ---------------------------------------------------------------------------
def extract_dynamic(card, now):
    """Extract dynamic info from a single card element."""
    dyn = {"id": None, "up_name": "", "type": "unknown", "content": "",
           "time_text": "", "time_dt": None, "url": ""}

    # B站动态卡片没有 data-did 属性，尝试从内部链接提取动态ID
    try:
        # 视频卡片的链接格式: //www.bilibili.com/video/BVxxxx/
        link = card.query_selector("a[href*='bilibili.com/video/']")
        if link:
            href = link.get_attribute("href") or ""
            # 提取BV号作为标识
            m = re.search(r"/(BV\w+)/?", href)
            if m:
                dyn["id"] = m.group(1)
                dyn["url"] = f"https:{href.split('?')[0]}"
    except Exception:
        pass

    # 如果没有找到视频链接，尝试从其他链接提取
    if not dyn["id"]:
        try:
            links = card.query_selector_all("a[href]")
            for link_el in links:
                href = link_el.get_attribute("href") or ""
                # 动态链接格式: /dynamic/ 或 t.bilibili.com/
                m = re.search(r"t\.bilibili\.com/(\d+)", href)
                if m:
                    dyn["id"] = m.group(1)
                    dyn["url"] = f"https://t.bilibili.com/{m.group(1)}"
                    break
        except Exception:
            pass

    try:
        up_el = card.query_selector(SELECTORS["up_name"])
        if up_el:
            dyn["up_name"] = up_el.inner_text().strip()
    except Exception:
        pass

    try:
        time_el = card.query_selector(SELECTORS["dyn_time"])
        if time_el:
            dyn["time_text"] = time_el.inner_text().strip()
            dyn["time_dt"] = parse_bilibili_time(dyn["time_text"], now)
    except Exception:
        pass

    try:
        content = card.query_selector(SELECTORS["dyn_content"])
        if content:
            # 视频动态
            video_card = content.query_selector(SELECTORS["dyn_video_card"])
            if video_card:
                dyn["type"] = "video"
                title_el = content.query_selector(SELECTORS["dyn_video_title"])
                if title_el:
                    dyn["content"] = title_el.inner_text().strip()
            # 专栏/图文动态
            elif content.query_selector(SELECTORS["dyn_card_article"]):
                dyn["type"] = "article"
                title_el = content.query_selector(SELECTORS["dyn_card_article_title"])
                if title_el:
                    dyn["content"] = title_el.inner_text().strip()
            # 纯文字动态
            elif content.query_selector(SELECTORS["dyn_text"]):
                dyn["type"] = "text"
                text_el = content.query_selector(SELECTORS["dyn_text"])
                if text_el:
                    full_text = text_el.inner_text().strip()
                    dyn["content"] = full_text[:100] + ("..." if len(full_text) > 100 else "")
    except Exception:
        pass

    # 如果内容为空，尝试从内容区提取任意文本
    if not dyn["content"]:
        try:
            content = card.query_selector(SELECTORS["dyn_content"])
            if content:
                full_text = content.inner_text().strip()
                # 取前100字符
                dyn["content"] = full_text[:100] + ("..." if len(full_text) > 100 else "")
        except Exception:
            pass

    return dyn


def collect_dynamics(page, cfg):
    """Collect all dynamics on the page, scrolling until time window is exceeded."""
    now = datetime.now()
    hours_back = cfg["hours_back"]
    cutoff = now - timedelta(hours=hours_back)
    max_scrolls = cfg["max_scroll_attempts"]
    wait_ms = cfg["scroll_wait_ms"]

    print("[collect] Waiting for dynamic list to load...")
    try:
        page.wait_for_selector(SELECTORS["dyn_list"], timeout=15000)
    except Exception:
        print("[collect] Dynamic list container not found. Page may have changed.")
        print(f"[collect] Current URL: {page.url}")
        try:
            screenshot_path = SCRIPT_DIR / "debug_screenshot.png"
            page.screenshot(path=str(screenshot_path), full_page=True)
            print(f"[collect] Debug screenshot saved: {screenshot_path}")
        except Exception:
            pass
        return []

    seen_ids = set()
    all_dynamics = []
    no_new_count = 0

    for scroll_idx in range(max_scrolls):
        cards = page.query_selector_all(SELECTORS["dyn_item"])
        print(f"[collect] Scroll {scroll_idx + 1}/{max_scrolls}: {len(cards)} cards visible")

        new_this_scroll = 0
        oldest_time_this_scroll = now
        for card in cards:
            dyn = extract_dynamic(card, now)
            # 去重：优先用动态ID，没有ID则用 UP名+时间+内容前50字 组合作为key
            dedup_key = dyn["id"]
            if not dedup_key:
                dedup_key = f"{dyn['up_name']}_{dyn['time_text']}_{dyn['content'][:50]}"
            if dedup_key in seen_ids:
                continue
            seen_ids.add(dedup_key)
            all_dynamics.append(dyn)
            new_this_scroll += 1
            if dyn["time_dt"] and dyn["time_dt"] != datetime.min:
                oldest_time_this_scroll = min(oldest_time_this_scroll, dyn["time_dt"])

        print(f"[collect]   New this scroll: {new_this_scroll}, total: {len(all_dynamics)}")

        if oldest_time_this_scroll < cutoff:
            print(f"[collect] Reached dynamics older than {hours_back}h window. Stopping.")
            break

        if new_this_scroll == 0:
            no_new_count += 1
            if no_new_count >= 3:
                print("[collect] No new dynamics for 3 scrolls. Stopping.")
                break
        else:
            no_new_count = 0

        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        page.wait_for_timeout(wait_ms)

    filtered = []
    for dyn in all_dynamics:
        if not dyn["time_dt"] or dyn["time_dt"] == datetime.min:
            if any(k in dyn["time_text"] for k in ["刚刚", "分钟前", "小时前"]):
                filtered.append(dyn)
            continue
        if dyn["time_dt"] >= cutoff:
            filtered.append(dyn)

    deduped = []
    seen = set()
    for dyn in filtered:
        key = dyn["id"] or f"{dyn['up_name']}_{dyn['content'][:20]}"
        if key in seen:
            continue
        seen.add(key)
        deduped.append(dyn)

    print(f"[collect] Total collected: {len(all_dynamics)}, in window: {len(deduped)}")
    return deduped


# ---------------------------------------------------------------------------
# Result formatting (output to stdout + result.md, no push API call)
# ---------------------------------------------------------------------------
def format_result(dynamics, hours_back):
    """Format dynamics into a Markdown result string for the WorkBuddy agent."""
    if not dynamics:
        return f"## B站动态更新\n\n近 {hours_back} 小时暂无新动态。"

    lines = [f"## B站动态更新（近 {hours_back} 小时）", ""]
    lines.append(f"共 **{len(dynamics)}** 条新动态")
    lines.append("")
    for i, dyn in enumerate(dynamics, 1):
        type_label = {"video": "视频", "article": "专栏", "text": "动态"}.get(dyn["type"], "动态")
        time_str = dyn["time_text"] or (dyn["time_dt"].strftime("%H:%M") if dyn["time_dt"] != datetime.min else "")
        lines.append(f"### {i}. {dyn['up_name']} · {time_str}")
        lines.append(f"**[{type_label}]** {dyn['content']}")
        if dyn["url"]:
            lines.append(f"[查看详情]({dyn['url']})")
        lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# QQ Bot API push
# ---------------------------------------------------------------------------
def get_qq_access_token(app_id, app_secret):
    """Get QQ Bot access token via HTTP API."""
    import urllib.request
    data = json.dumps({"appId": app_id, "clientSecret": app_secret}).encode()
    req = urllib.request.Request(
        QQ_TOKEN_URL, data=data,
        headers={"Content-Type": "application/json"}
    )
    resp = urllib.request.urlopen(req, timeout=10)
    result = json.loads(resp.read())
    return result["access_token"]


def send_qq_message(access_token, openid, content, msg_type=0):
    """Send a C2C message to a QQ user via Bot API."""
    import urllib.request, urllib.error

    # QQ Bot text message limit: 2000 chars for text, but practically shorter is better
    # Split long content into chunks if needed
    max_len = 1800
    if len(content) > max_len:
        chunks = []
        for i in range(0, len(content), max_len):
            chunks.append(content[i:i+max_len])
    else:
        chunks = [content]

    headers = {
        "Authorization": f"QQBot {access_token}",
        "Content-Type": "application/json",
    }

    for i, chunk in enumerate(chunks):
        body = json.dumps({
            "content": chunk,
            "msg_type": msg_type,
        }).encode()
        url = f"{QQ_API_BASE}/v2/users/{openid}/messages"
        req = urllib.request.Request(url, data=body, headers=headers, method="POST")
        try:
            resp = urllib.request.urlopen(req, timeout=15)
            result = json.loads(resp.read())
            print(f"[qq-push] Chunk {i+1}/{len(chunks)} sent: id={result.get('id', 'N/A')}")
        except urllib.error.HTTPError as e:
            err_body = e.read().decode("utf-8", errors="replace")
            print(f"[qq-push] Chunk {i+1}/{len(chunks)} failed: {e.code} {err_body[:300]}")
            return False
    return True


def push_via_qq_bot(cfg, result_text, dyn_count):
    """Push the result to the user's QQ via QQ Bot API."""
    import urllib.error

    # Check if openid is saved
    if not OPENID_PATH.exists():
        print("\n[qq-push] OpenID not found. To enable QQ push:")
        print("  1. Temporarily close WorkBuddy")
        print("  2. Run: python capture_openid.py")
        print("  3. Send any message to the bot on QQ")
        print("  4. Reopen WorkBuddy")
        print(f"\n[qq-push] Result saved to {RESULT_PATH} for manual viewing.")
        return False

    openid = OPENID_PATH.read_text(encoding="utf-8").strip()
    if not openid:
        print("[qq-push] OpenID file is empty. Re-run capture_openid.py")
        return False

    # Get config
    app_id = cfg.get("qq_app_id", "")
    app_secret = cfg.get("qq_app_secret", "")

    print(f"\n[qq-push] Getting access token (appId={app_id})...")
    try:
        token = get_qq_access_token(app_id, app_secret)
        print(f"[qq-push] Token: {token[:30]}...")
    except Exception as e:
        print(f"[qq-push] Failed to get token: {e}")
        return False

    # Prepare message (QQ text messages have length limits, keep it concise)
    title = f"B站动态更新 - {dyn_count}条新动态"
    # Send a short summary first, then the full content
    # QQ Bot text message: max ~2000 chars, but URL needs pre-configuration
    # Remove markdown links (QQ Bot doesn't render them in text mode)
    import re
    clean_text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r"\1: \2", result_text)
    clean_text = clean_text.replace("###", "").replace("##", "").replace("**", "")

    print(f"[qq-push] Sending to openid={openid[:20]}...")
    success = send_qq_message(token, openid, clean_text, msg_type=0)

    if success:
        print("[qq-push] ✅ Message sent to QQ successfully!")
    else:
        print("[qq-push] ❌ Failed to send message. Check error above.")

    return success


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description="Bilibili Dynamic Monitor (QQ Push via WorkBuddy)")
    parser.add_argument("--setup", action="store_true", help="Install dependencies")
    parser.add_argument("--login", action="store_true", help="Force re-login (delete saved state)")
    args = parser.parse_args()

    if args.setup:
        run_setup()
        return

    maybe_relaunch_in_venv()

    cfg = load_config()

    if args.login and STORAGE_STATE_PATH.exists():
        print(f"[login] Deleting {STORAGE_STATE_PATH} for re-login.")
        STORAGE_STATE_PATH.unlink()

    sync_playwright = import_playwright()

    with sync_playwright() as p:
        launch_opts = {"headless": cfg["headless"]}
        context_opts = {
            "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:120.0) Gecko/20100101 Firefox/120.0",
            "viewport": {"width": 1280, "height": 900},
        }

        if STORAGE_STATE_PATH.exists():
            print(f"[login] Loading saved state: {STORAGE_STATE_PATH}")
            context_opts["storage_state"] = str(STORAGE_STATE_PATH)
            browser = p.firefox.launch(**launch_opts)
            context = browser.new_context(**context_opts)
        else:
            print("[login] No saved state. Will require manual login.")
            browser = p.firefox.launch(**launch_opts)
            context = browser.new_context(**context_opts)

        page = context.new_page()

        if not ensure_login(context, page):
            print("[error] Login required. Re-run after logging in.")
            browser.close()
            sys.exit(1)

        dynamics = collect_dynamics(page, cfg)
        browser.close()

    # Format result
    result = format_result(dynamics, cfg["hours_back"])

    # Write to result.md for fallback
    with open(RESULT_PATH, "w", encoding="utf-8") as f:
        f.write(result)
    print(f"\n[result] Result written to {RESULT_PATH}")

    # Print to stdout
    print("\n" + "=" * 60)
    print("RESULT_START")
    print(result)
    print("RESULT_END")
    print("=" * 60)

    if not dynamics:
        print(f"[done] No new dynamics in the last {cfg['hours_back']} hours.")
        return

    print(f"[done] Found {len(dynamics)} new dynamics.")

    # Push via QQ Bot API
    push_via_qq_bot(cfg, result, len(dynamics))


if __name__ == "__main__":
    main()
