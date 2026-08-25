"""免费新闻源抓取。

v1 支持两种源：
  - rss : 解析 XML feed（新华网/人民网时政频道）
  - html: 解析政府网站列表页（中国政府网「要闻」列表，尽力而为）

设计原则：任何单源失败只记日志、不拖垮整体；列表页结构变化属于可接受的
维护成本（方案 05 中已声明），抓取失败时流水线自动降级为只生成话题卡。
"""
from __future__ import annotations

import logging
import re
from datetime import datetime

import httpx
from bs4 import BeautifulSoup

log = logging.getLogger(__name__)

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")

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


def fetch_rss(source: dict) -> list[dict]:
    """解析 RSS/Atom feed，返回 [{title, url, source, date, summary}]。"""
    url = source["url"]
    xml = _fetch(url)
    soup = BeautifulSoup(xml, "xml")
    items = []
    for node in soup.find_all("item"):
        title = _clean(node.find("title").get_text() if node.find("title") else "")
        link = _clean(node.find("link").get_text() if node.find("link") else "")
        desc = _strip_html(node.find("description").get_text() if node.find("description") else "")
        pub = _clean(node.find("pubDate").get_text() if node.find("pubDate") else "")
        if not title or not link:
            continue
        items.append({
            "title": title,
            "url": link,
            "source": source["name"],
            "date": pub[:10] if pub else datetime.now().date().isoformat(),
            "summary": desc,
        })
    return items


def fetch_html_list(source: dict) -> list[dict]:
    """中国政府网「要闻」列表页：取出 <li> 内标题+链接，摘要留空。"""
    url = source["url"]
    html = _fetch(url)
    soup = BeautifulSoup(html, "html.parser")
    items = []
    seen = set()
    for a in soup.select("a[href]"):
        title = _clean(a.get_text())
        href = a.get("href", "")
        if not title or len(title) < 8:
            continue
        if not href.startswith("http"):
            href = "https://www.gov.cn" + href
        if href in seen:
            continue
        seen.add(href)
        items.append({
            "title": title,
            "url": href,
            "source": source["name"],
            "date": datetime.now().date().isoformat(),
            "summary": "",
        })
    return items


def fetch_source(source: dict) -> list[dict]:
    kind = source.get("kind", "rss")
    if kind == "rss":
        return fetch_rss(source)
    if kind == "html":
        return fetch_html_list(source)
    log.warning("未知源类型 %s：%s", kind, source.get("name"))
    return []


def fetch_news(sources: list[dict], limit: int = 5, keywords: list[str] | None = None) -> list[dict]:
    """聚合所有源 → 关键词过滤 → 去重 → 截取 limit 条。单源失败降级跳过。"""
    keywords = keywords or []
    seen = set()
    out: list[dict] = []
    for source in sources:
        try:
            for item in fetch_source(source):
                title = item["title"]
                if not keywords or any(k in title for k in keywords):
                    key = (title[:40], item["url"])
                    if key not in seen:
                        seen.add(key)
                        out.append(item)
        except Exception as e:  # noqa: BLE001 —— 单源失败不拖垮整体
            log.warning("抓取源失败 %s: %s", source.get("name"), e)
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
