import re
import time
from datetime import datetime, timezone

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from webdriver_manager.chrome import ChromeDriverManager

from core.event_bus import bus
from functions.func_memory import vault

try:
    from functions.func_actions import stop_event
except ImportError:
    stop_event = None


CDKEY_LEDGER_VERSION = 1
DEFAULT_CDKEY_LEDGER_KEY = "mingchao_cdkeys"


class ChinaChromeDriverManager(ChromeDriverManager):
    def _get_driver_download_url(self, version, driver_type, os_type, os_arch):
        original_url = super()._get_driver_download_url(
            version, driver_type, os_type, os_arch
        )
        return original_url.replace(
            "storage.googleapis.com/chrome-for-testing-public",
            "npmmirror.com/mirrors/chrome-for-testing",
        ).replace(
            "chrome-for-testing-public.googleusercontent.com",
            "npmmirror.com/mirrors/chrome-for-testing",
        )


def _utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _interruptible_wait(seconds):
    if stop_event and stop_event.wait(timeout=max(0.0, float(seconds))):
        raise InterruptedError("收到紧急刹车")
    if not stop_event:
        time.sleep(seconds)


def _raise_if_stopped():
    if stop_event and stop_event.is_set():
        raise InterruptedError("收到紧急刹车")


def _normalise_code(code):
    return str(code or "").strip().upper()


def _is_rejected_cdkey(code):
    """Reject known page metadata that looks like a redemption code."""
    return _normalise_code(code).startswith("USER")


def _normalise_ledger(raw):
    raw = raw if isinstance(raw, dict) else {}
    discovered = raw.get("discovered", {})
    processed = raw.get("processed", {})

    if isinstance(discovered, list):
        discovered = {code: {} for code in discovered}
    if isinstance(processed, list):
        processed = {code: {"result": "legacy"} for code in processed}

    clean_discovered = {}
    for code, metadata in (discovered or {}).items():
        normalised = _normalise_code(code)
        if normalised and not _is_rejected_cdkey(normalised):
            clean_discovered[normalised] = (
                dict(metadata) if isinstance(metadata, dict) else {}
            )

    clean_processed = {}
    for code, metadata in (processed or {}).items():
        normalised = _normalise_code(code)
        if normalised and not _is_rejected_cdkey(normalised):
            clean_processed[normalised] = (
                dict(metadata) if isinstance(metadata, dict) else {"result": str(metadata)}
            )

    seen_posts = []
    for link in raw.get("seen_posts", []) or []:
        link = str(link or "").strip()
        if link and link not in seen_posts:
            seen_posts.append(link)

    return {
        "version": CDKEY_LEDGER_VERSION,
        "discovered": clean_discovered,
        "processed": clean_processed,
        "seen_posts": seen_posts,
    }


def load_cdkey_ledger(ledger_key=DEFAULT_CDKEY_LEDGER_KEY):
    """Load the transactional code ledger and import the old crawler memory once."""
    ledger = _normalise_ledger(vault.read(ledger_key))

    # The old implementation wrote a code before the game had used it.  Import
    # those values as discovered/pending, never as processed, so failed historic
    # attempts are not silently lost.
    legacy_codes = vault.read("aegis_seen_cdkeys") or []
    if isinstance(legacy_codes, str):
        legacy_codes = [legacy_codes]
    for code in legacy_codes:
        normalised = _normalise_code(code)
        if (
            normalised
            and not _is_rejected_cdkey(normalised)
            and normalised not in ledger["discovered"]
        ):
            ledger["discovered"][normalised] = {
                "source": "legacy_aegis_seen_cdkeys",
                "discovered_at": _utc_now(),
            }

    legacy_posts = vault.read("aegis_seen_posts") or []
    if isinstance(legacy_posts, str):
        legacy_posts = [legacy_posts]
    for link in legacy_posts:
        link = str(link or "").strip()
        if link and link not in ledger["seen_posts"]:
            ledger["seen_posts"].append(link)

    return ledger


def save_cdkey_ledger(ledger, ledger_key=DEFAULT_CDKEY_LEDGER_KEY):
    ledger = _normalise_ledger(ledger)
    if not vault.write(ledger_key, ledger):
        raise RuntimeError(f"兑换码账本写入失败：{ledger_key}")
    return ledger


def pending_cdkeys(ledger):
    ledger = _normalise_ledger(ledger)
    processed = set(ledger["processed"])
    return [code for code in ledger["discovered"] if code not in processed]


def mark_cdkey_processed(
    code, result="兑换成功", ledger_key=DEFAULT_CDKEY_LEDGER_KEY
):
    """Commit one attempted code. Only this function removes it from pending."""
    code = _normalise_code(code)
    if not code:
        raise ValueError("无法记录空兑换码")

    ledger = load_cdkey_ledger(ledger_key)
    ledger["discovered"].setdefault(
        code,
        {"source": "manual", "discovered_at": _utc_now()},
    )
    ledger["processed"][code] = {
        "result": str(result or "已处理"),
        "processed_at": _utc_now(),
    }
    save_cdkey_ledger(ledger, ledger_key)
    return ledger["processed"][code]


def _create_chrome_driver(options):
    """Use the China mirror first; keep Selenium Manager as a fallback."""
    try:
        bus.log_emitted.emit("INFO", "Network", "正在使用国内镜像准备 Chrome 驱动...")
        _raise_if_stopped()
        return webdriver.Chrome(
            service=Service(ChinaChromeDriverManager().install()), options=options
        )
    except Exception as mirror_error:
        bus.log_emitted.emit(
            "WARN",
            "Network",
            f"镜像驱动初始化失败，切换 Selenium Manager: {mirror_error}",
        )
        return webdriver.Chrome(options=options)


def hal_scrape_cdkeys(
    url: str,
    keywords_str: str,
    regex_pattern: str,
    max_scroll: int,
    ledger_key: str = DEFAULT_CDKEY_LEDGER_KEY,
):
    """Scrape candidate codes and return every unprocessed code in the ledger.

    Discovery and completion are deliberately separate transactions. A browser,
    focus, paste, or game failure therefore leaves the code pending for tomorrow.
    """
    ledger = load_cdkey_ledger(ledger_key)
    initial_pending = pending_cdkeys(ledger)
    bus.log_emitted.emit(
        "INFO",
        "Network",
        (
            f"已加载兑换码账本: {len(ledger['discovered'])} 个发现记录，"
            f"{len(ledger['processed'])} 个已处理，{len(initial_pending)} 个待处理"
        ),
    )

    try:
        code_pattern = re.compile(regex_pattern)
    except re.error as error:
        raise ValueError(f"兑换码正则编译失败: {error}") from error

    keywords = [
        keyword.strip()
        for keyword in keywords_str.replace("|", ",").split(",")
        if keyword.strip()
    ] or ["兑换码"]

    options = Options()
    options.add_argument("--headless=new")
    options.add_argument("--disable-gpu")
    options.add_argument("--no-sandbox")
    options.add_argument("--log-level=3")
    options.add_argument("--window-size=1440,1200")

    driver = None
    scrape_error = None
    try:
        bus.log_emitted.emit("INFO", "Network", "正在初始化 Chrome 静默驱动...")
        driver = _create_chrome_driver(options)
        _raise_if_stopped()
        driver.set_page_load_timeout(45)
        driver.get(url)
        _interruptible_wait(2)

        try:
            driver.find_element(
                By.XPATH,
                "//span[contains(text(), '帖子')] | //a[contains(text(), '帖子')]",
            ).click()
            _interruptible_wait(2)
        except Exception:
            pass

        last_height = driver.execute_script("return document.body.scrollHeight")
        for _ in range(max(0, int(max_scroll))):
            _raise_if_stopped()
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            _interruptible_wait(1.5)
            new_height = driver.execute_script("return document.body.scrollHeight")
            if new_height == last_height:
                break
            last_height = new_height

        # Multiple keywords mean OR. Requiring every word on the same DOM node
        # made the old crawler miss ordinary post cards.
        xpath_parts = [f"contains(text(), {repr(keyword)})" for keyword in keywords]
        elements = driver.find_elements(By.XPATH, f"//*[{ ' or '.join(xpath_parts) }]")

        seen_posts = set(ledger["seen_posts"])
        for element in elements:
            _raise_if_stopped()
            title = element.text.strip()
            if not title:
                continue
            try:
                link_element = element.find_element(
                    By.XPATH, "./ancestor::a[1] | .//a[1]"
                )
                link = str(link_element.get_attribute("href") or "").strip()
            except Exception:
                continue
            if not link or link in seen_posts:
                continue

            driver.execute_script("window.open('');")
            driver.switch_to.window(driver.window_handles[-1])
            post_loaded = False
            try:
                driver.get(link)
                _interruptible_wait(2)
                body_text = driver.find_element(By.TAG_NAME, "body").text.upper()
                codes = list(dict.fromkeys(code_pattern.findall(body_text)))
                post_loaded = True
                for code in codes:
                    code = _normalise_code(code)
                    if (
                        not code
                        or _is_rejected_cdkey(code)
                        or code in ledger["discovered"]
                    ):
                        continue
                    ledger["discovered"][code] = {
                        "source_url": link,
                        "source_title": title,
                        "discovered_at": _utc_now(),
                    }
                    bus.log_emitted.emit(
                        "SUCCESS",
                        "Network",
                        f"截获候选兑换码 {code}，已加入待处理队列",
                    )
            finally:
                driver.close()
                driver.switch_to.window(driver.window_handles[0])

            # Only suppress a post after its body was actually read. A timeout
            # must remain retryable on the next daily run.
            if post_loaded:
                seen_posts.add(link)
                ledger["seen_posts"].append(link)

    except InterruptedError as error:
        scrape_error = error
        bus.log_emitted.emit("WARN", "Network", "收到紧急刹车，网页嗅探已停止")
    except Exception as error:
        scrape_error = error
        bus.log_emitted.emit("ERROR", "Network", f"兑换码抓取异常: {error}")
    finally:
        save_cdkey_ledger(ledger, ledger_key)
        if driver is not None:
            try:
                driver.quit()
            except Exception:
                pass

    pending = pending_cdkeys(ledger)
    if stop_event and stop_event.is_set():
        return pending
    if scrape_error and not pending:
        raise RuntimeError(f"网页抓取失败，且账本中没有可继续处理的兑换码: {scrape_error}")
    if scrape_error and pending:
        bus.log_emitted.emit(
            "WARN",
            "Network",
            f"网页暂时不可用，继续处理账本中已有的 {len(pending)} 个待兑换码",
        )
    return pending
