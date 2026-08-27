"""免费新闻源抓取（V2）。

源类型：
  - rss  : 解析 XML feed（备用）
  - yaowen: 权威源要闻区 HTML（中国政府网首页/新华网时政/人民日报首页）—— V2 主力

V2 关键改动：
  - 日期从 URL 提取（/2026/0827/ 或 /20260827/ 或 /202608/content_），不信任页面 pubDate
  - 14 天时效窗口：仅保留近 14 天内的新闻，旧闻一律丢弃
  - 不再按关键词过滤标题（关键词过滤曾导致真正重点被漏掉），由 AI 挑选

设计原则：任何单源失败只记日志、不拖垮整体；抓取失败时流水线自动降级。
"""
from __future__ import annotations

import logging
import re
from datetime import date, datetime, timedelta

import httpx
from bs4 import BeautifulSoup

log = logging.getLogger(__name__)

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")

FRESH_DAYS = 14  # 时效窗口：仅保留近 14 天

# 干净摘要：去掉多余空白 + 剥除 HTML 标签
def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def _strip_html(text: str) -> str:
    """剥除 RSS description 里的 HTML 标签（<p style=…> 等），保留纯文本。"""
    if not text:
        return ""
    soup = BeautifulSoup(text, "html.parser")
    return _clean(soup.get_text(" ", strip=True))


def _fetch(url: str, timeout: float = 15.0) -> str:
    resp = httpx.get(url, headers={"User-Agent": UA}, timeout=timeout, follow_redirects=True)
    resp.raise_for_status()
    return resp.text


# 标题噪声：导航/链接栏/纯栏目名
_TITLE_NOISE = ("首页", "返回", "登录", "注册", "搜索", "更多", "专题", ">>", "·", "|",
                "人民日报社", "版权", "网站地图", "联系我们", "客户端", "手机版")


def date_from_url(url: str) -> str | None:
    """从 URL 提取发布日期（ISO 格式）。支持：
    /2026/0827/... -> 2026-08-27
    /20260827/...  -> 2026-08-27
    /202608/content_... -> 2026-08-01（gov.cn 仅到月）
    """
    m = re.search(r"/(20\d{2})/(\d{4})/", url)
    if m:
        return f"{m.group(1)}-{m.group(2)[:2]}-{m.group(2)[2:]}"
    m = re.search(r"/(20\d{6})/", url)
    if m:
        d = m.group(1)
        return f"{d[:4]}-{d[4:6]}-{d[6:]}"
    m = re.search(r"/(20\d{4})/content_", url)
    if m:
        return f"{m.group(1)[:4]}-{m.group(1)[4:6]}-01"
    return None


def _is_fresh(date_str: str | None, today: date | None = None) -> bool:
    """14 天时效窗口判断。date_str 为 None 视为失效。"""
    if not date_str:
        return False
    try:
        d = datetime.strptime(date_str, "%Y-%m-%d").date()
    except ValueError:
        return False
    today = today or date.today()
    return today - timedelta(days=FRESH_DAYS) <= d <= today


def fetch_yaowen(source: dict) -> list[dict]:
    """抓取权威源要闻区：提取标题+链接，日期从 URL 提取，时效校验。"""
    url = source["url"]
    html = _fetch(url)
    soup = BeautifulSoup(html, "html.parser")
    items = []
    seen = set()
    today = date.today()
    for a in soup.find_all("a", href=True):
        title = _clean(a.get_text())
        href = a["href"]
        if not title or not (10 <= len(title) <= 60):
            continue
        if any(n in title for n in _TITLE_NOISE):
            continue
        if href.startswith("/"):
            # 相对链接补全
            from urllib.parse import urljoin
            href = urljoin(url, href)
        d = date_from_url(href)
        if not _is_fresh(d, today):
            continue  # 无日期或超过 14 天窗口 → 丢弃
        if href in seen:
            continue
        seen.add(href)
        items.append({
            "title": title,
            "url": href,
            "source": source["name"],
            "date": d,
            "summary": "",
        })
    return items


def fetch_rss(source: dict) -> list[dict]:
    """解析 RSS/Atom feed（备用源）。日期取 pubDate，同样过 14 天窗口。"""
    url = source["url"]
    xml = _fetch(url)
    soup = BeautifulSoup(xml, "xml")
    items = []
    today = date.today()
    for node in soup.find_all("item"):
        title = _clean(node.find("title").get_text() if node.find("title") else "")
        link = _clean(node.find("link").get_text() if node.find("link") else "")
        desc = _strip_html(node.find("description").get_text() if node.find("description") else "")
        pub = _clean(node.find("pubDate").get_text() if node.find("pubDate") else "")
        if not title or not link:
            continue
        d = pub[:10] if pub else None
        if not _is_fresh(d, today):
            continue
        items.append({
            "title": title,
            "url": link,
            "source": source["name"],
            "date": d or today.isoformat(),
            "summary": desc,
        })
    return items


def fetch_html_list(source: dict) -> list[dict]:
    """通用 HTML 列表页抓取（兜底，日期从 URL 提取 + 时效校验）。"""
    url = source["url"]
    html = _fetch(url)
    soup = BeautifulSoup(html, "html.parser")
    items = []
    seen = set()
    today = date.today()
    for a in soup.select("a[href]"):
        title = _clean(a.get_text())
        href = a.get("href", "")
        if not title or len(title) < 8:
            continue
        if any(n in title for n in _TITLE_NOISE):
            continue
        from urllib.parse import urljoin
        href = urljoin(url, href)
        d = date_from_url(href)
        if not _is_fresh(d, today):
            continue
        if href in seen:
            continue
        seen.add(href)
        items.append({
            "title": title,
            "url": href,
            "source": source["name"],
            "date": d or today.isoformat(),
            "summary": "",
        })
    return items


def fetch_source(source: dict) -> list[dict]:
    kind = source.get("kind", "yaowen")
    if kind == "rss":
        return fetch_rss(source)
    if kind in ("html", "yaowen"):
        return fetch_yaowen(source) if kind == "yaowen" else fetch_html_list(source)
    log.warning("未知源类型 %s：%s", kind, source.get("name"))
    return []


def fetch_news(sources: list[dict], limit: int = 30) -> list[dict]:
    """聚合所有源 → 按日期倒序 → 去重 → 截取 limit 条。单源失败降级跳过。

    V2：不按关键词过滤（那会漏掉真正重点），由上层 AI 从全量中挑选。
    """
    seen = set()
    out: list[dict] = []
    for source in sources:
        try:
            for item in fetch_source(source):
                key = (item["title"][:40], item["url"])
                if key not in seen:
                    seen.add(key)
                    out.append(item)
        except Exception as e:  # noqa: BLE001 —— 单源失败不拖垮整体
            log.warning("抓取源失败 %s: %s", source.get("name"), e)
    out.sort(key=lambda it: it.get("date", ""), reverse=True)
    return out[:limit]


def fetch_phrase_source(source: dict) -> list[str]:
    """抓取一个语段素材页，提取正文段落。

    返回候选语段列表（已清洗、去导航噪声）。页面结构变化导致的失败由调用方降级。
    """
    url = source["url"]
    html = _fetch(url)
    soup = BeautifulSoup(html, "html.parser")
    # 移除脚本/样式/导航/广告
    for tag in soup(["script", "style", "nav", "header", "footer", "aside"]):
        tag.decompose()
    # 导航/UI/广告噪声关键词：命中即丢弃
    noise_words = ("首页", "备考资料", "咨询", "扫码", "关注", "下载", "登录",
                   "注册", "课程", "题库", "模考", "报名", "成绩", "人工",
                   ">", "报名入口", "微信", "APP", "点击", "了解更多", "下一篇",
                   "华图", "中公", "粉笔", "教育机构", "培训机构", "领航者",
                   "助力万千", "圆梦", "教综", "教师资格", "笔试网课", "本地课程",
                   "考试信息", "扫码添加")
    # 收集正文段落
    candidates = []
    seen = set()
    for node in soup.find_all(["p", "li", "h1", "h2", "h3"]):
        text = _clean(node.get_text())
        # 语段候选：15~200 字，非纯数字/链接
        if not (15 <= len(text) <= 200):
            continue
        if any(w in text for w in noise_words):
            continue
        if text in seen:
            continue
        seen.add(text)
        candidates.append(text)
    return candidates
