"""每日流水线：抓取新闻 → DeepSeek 生成草稿 → 写入本地 JSON。

run_daily():
  1. 抓取真实新闻（失败则降级，跳过热点只做话题卡）
  2. 前 N 条新闻 → analyze_hotspot → 写 hotspots 草稿
  3. 按主题轮转生成 N 张话题卡 → 写 topic_cards 草稿
  4. 抓取语段素材页 → AI 改稿为标准格式 → 去重 → 写 phrases 草稿
  5. 更新 config.last_update_date

run_catchup():
  启动时若 last_update_date 落后于今天（≤ catchup_limit 天），
  对缺失的每一天补拉。补拉的天只生成话题卡和语段（过去的新闻没有抓取意义）。

所有生成项一律 status=草稿，必须人工审核后入库。
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta

from . import fetchers
from .llm import DeepSeekClient, LLMError
from .store import THEMES, JsonStore, today_str

log = logging.getLogger(__name__)


def _dates_since_last(last: str | None, cap: int) -> list[str]:
    """返回 [last+1, today] 之间缺失的日期列表（最多 cap 天）。"""
    today = date.today()
    if not last:
        return [today.isoformat()]
    try:
        start = datetime.strptime(last, "%Y-%m-%d").date() + timedelta(days=1)
    except ValueError:
        return [today.isoformat()]
    if start > today:
        return []
    days = (today - start).days + 1
    return [(start + timedelta(days=i)).isoformat() for i in range(min(days, cap))]


class Pipeline:
    def __init__(self, store: JsonStore, llm: DeepSeekClient):
        self.store = store
        self.llm = llm
        self._running = False

    @property
    def running(self) -> bool:
        return self._running

    def run_daily(self, target_date: str | None = None, progress=None) -> dict:
        """跑一天：抓新闻 + 生成话题卡 + 搜集语段。target_date 默认今天；非今天只做话题卡和语段。"""
        if self._running:
            return {"ok": False, "error": "已有流水线正在运行"}
        self._running = True
        target = target_date or today_str()
        cfg = self.store.get_config()
        result = {"date": target, "hotspots": 0, "cards": 0, "phrases": 0, "errors": []}
        # 已存在内容（用于去重，避免同日重复生成）
        existing_hot_titles = {it.get("title", "") for it in self.store.list_all("hotspots")}
        existing_card_topics = {it.get("topic", "") for it in self.store.list_all("topic_cards")}
        # 当天已生成的卡片主题（同日不重复，次日重新生成）
        existing_card_themes = {it.get("theme", "") for it in self.store.list_all("topic_cards")
                                if it.get("date") == target}
        try:
            # 1) 真实热点：只有当天才抓新闻 → AI 挑选重点 → 逐条分析
            if target == today_str():
                candidates = fetchers.fetch_news(
                    cfg.get("sources", []),
                    limit=cfg.get("daily_hotspots", 5) * 6,  # 抓全量候选供挑选
                )
                if candidates:
                    # 先过滤已入库的标题，减少 AI 挑选负担
                    fresh_cands = [c for c in candidates if c["title"] not in existing_hot_titles]
                    if progress:
                        progress(f"候选新闻 {len(fresh_cands)} 条，AI 挑选重点…")
                    picked = self._pick_hotspots(fresh_cands, cfg.get("daily_hotspots", 5))
                    if not picked and fresh_cands:
                        # AI 挑选失败（无 key/超时）→ 降级：按最新日期取前 N 条
                        picked = fresh_cands[: cfg.get("daily_hotspots", 5)]
                        result["errors"].append("AI 挑选失败，已降级按最新新闻取前几条")
                    for item in picked:
                        if item["title"] in existing_hot_titles:
                            continue
                        existing_hot_titles.add(item["title"])
                        if progress:
                            progress(f"分析热点：{item['title'][:20]}…")
                        try:
                            analysis = self.llm.analyze_hotspot(
                                item["title"], item.get("summary", ""), item.get("source", ""))
                            self.store.create("hotspots", {
                                "date": target,
                                "title": item["title"],
                                "source": item.get("source", ""),
                                "url": item.get("url", ""),
                                "summary": item.get("summary", ""),
                                "why": item.get("why", ""),
                                "subjects": item.get("subjects", []),
                                **analysis,
                            })
                            result["hotspots"] += 1
                        except LLMError as e:
                            result["errors"].append(f"热点分析失败（{item['title'][:15]}…）：{e}")
                else:
                    result["errors"].append("新闻抓取失败或无近14天新闻，已跳过热点生成（可手动录入）")
            else:
                log.info("补拉日 %s：只生成话题卡和语段", target)

            # 2) 话题卡：主题轮转（该主题已有卡则跳过，避免同日重复）
            count = cfg.get("daily_cards", 5)
            themes = self._pick_themes(count, target)
            for theme in themes:
                if progress:
                    progress(f"生成话题卡：{theme}…")
                if theme in existing_card_themes:
                    continue  # 该主题已生成过，跳过
                existing_card_themes.add(theme)
                try:
                    card = self.llm.generate_topic_card(theme)
                    if card.get("topic") in existing_card_topics:
                        existing_card_themes.discard(theme)
                        continue
                    existing_card_topics.add(card.get("topic", ""))
                    self.store.create("topic_cards", {
                        "date": target,
                        "theme": theme,
                        **card,
                    })
                    result["cards"] += 1
                except LLMError as e:
                    result["errors"].append(f"话题卡生成失败（{theme}）：{e}")

            # 3) 语段搜集：素材页 → AI 改稿 → 去重 → 草稿
            phrase_count = cfg.get("daily_phrases", 3)
            if phrase_count > 0:
                try:
                    result["phrases"] = self._collect_phrases(
                        cfg.get("phrase_sources", []), phrase_count, progress)
                except Exception as e:  # noqa: BLE001 —— 语段搜集失败不拖垮整体
                    log.exception("语段搜集异常")
                    result["errors"].append(f"语段搜集失败：{e}")

            # 4) 更新 last_update_date：只有真正生成了内容才推进，
            #    否则启动补拉机制会误以为当天已更新而跳过。
            if result["hotspots"] + result["cards"] + result["phrases"] > 0:
                cfg = self.store.get_config()
                if not cfg["last_update_date"] or cfg["last_update_date"] < target:
                    self.store.set_config({"last_update_date": target})
            result["ok"] = not result["errors"] or (
                result["hotspots"] + result["cards"] + result["phrases"]) > 0
            return result
        finally:
            self._running = False

    def _collect_phrases(self, sources: list[dict], limit: int, progress=None) -> int:
        """从素材页抓候选语段 → 与库内去重 → AI 改稿 → 写草稿。返回新增条数。"""
        if not self.llm.configured:
            log.warning("未配置 API Key，跳过语段搜集")
            return 0
        existing = {p.get("text", "")[:50] for p in self.store.list_all("phrases")}
        # 依次扫描每个素材源，直到凑够 limit 条
        added = 0
        for source in sources:
            if added >= limit:
                break
            try:
                candidates = fetchers.fetch_phrase_source(source)
            except Exception as e:  # noqa: BLE001
                log.warning("语段素材页抓取失败 %s: %s", source.get("name"), e)
                continue
            for cand in candidates:
                if added >= limit:
                    break
                # 去重：正文前 50 字相似即跳过
                key = cand[:50]
                if key in existing:
                    continue
                existing.add(key)
                if progress:
                    progress(f"语段改稿：{cand[:18]}…")
                try:
                    phrase = self.llm.format_phrase(cand)
                    if not phrase.get("text") or len(phrase["text"]) < 10:
                        continue
                    self.store.create("phrases", {
                        "date": today_str(),
                        "text": phrase["text"],
                        "template": phrase.get("template", ""),
                        "examples": phrase.get("examples", []),
                        "position": phrase.get("position", []),
                        "theme": phrase.get("theme", []),
                        "technique": phrase.get("technique", []),
                        "usage": phrase.get("usage", ""),
                        "collected": False,
                        "used_count": 0,
                    })
                    added += 1
                except LLMError as e:
                    log.warning("语段改稿失败: %s", e)
        return added

    def _pick_hotspots(self, candidates: list[dict], limit: int) -> list[dict]:
        """AI 从候选新闻中挑选重点；无 key 或失败时降级按最新日期取前 limit 条。"""
        if not candidates:
            return []
        if not self.llm.configured:
            return candidates[:limit]
        try:
            picked = self.llm.pick_hotspots(candidates)
            picked = [p for p in picked if p.get("title")]
            # 若 AI 挑得不足，用剩余候选补齐
            if len(picked) < limit:
                picked_titles = {p["title"] for p in picked}
                for c in candidates:
                    if len(picked) >= limit:
                        break
                    if c["title"] not in picked_titles:
                        picked.append(c)
            return picked[:limit]
        except Exception as e:  # noqa: BLE001 —— 挑选失败降级
            log.warning("AI 挑选重点失败，降级: %s", e)
            return candidates[:limit]

    def run_catchup(self, progress=None) -> dict:
        """启动补拉：缺失天数 ≤ catchup_limit，逐天生成（只话题卡）。"""
        cfg = self.store.get_config()
        missing = _dates_since_last(cfg.get("last_update_date"), cfg.get("catchup_limit", 3))
        if not missing:
            return {"ok": True, "caught_up": [], "errors": []}
        caught, errors = [], []
        for day in missing:
            r = self.run_daily(day, progress)
            caught.append(day)
            errors.extend(r.get("errors", []))
        return {"ok": True, "caught_up": caught, "errors": errors}

    @staticmethod
    def _pick_themes(count: int, target_date: str) -> list[str]:
        """按日期做简单偏移轮转，避免每天生成相同主题。"""
        offset = sum(ord(c) for c in target_date) % len(THEMES)
        return [THEMES[(offset + i) % len(THEMES)] for i in range(min(count, len(THEMES)))]
