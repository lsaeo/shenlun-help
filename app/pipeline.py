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
from .store import THEMES, JsonStore, sucai_dir as _sucai_dir, today_str

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
        self._last_provider = getattr(llm, "model", "")  # 用于变更检测
        self._llm_fail_count = 0  # 本轮流水线内 LLM 连续失败次数（熔断用）

    @property
    def running(self) -> bool:
        return self._running

    def _report(self, step: str = "", message: str = "", done: int = 0, total: int = 0,
                progress=None, state: str = "running"):
        """统一进度上报：写 store 状态（前端轮询读）+ 调本地回调。"""
        if step:
            self.store.set_pipeline_status(state=state, step=step, message=message,
                                           done=done, total=total)
        if progress and message:
            progress(message)

    def _llm_failed(self, e: Exception) -> bool:
        """记录一次 LLM 失败；连续失败达 3 次返回 True（应熔断跳过剩余任务）。"""
        self._llm_fail_count += 1
        log.warning("LLM 调用失败(第%d次): %s", self._llm_fail_count, e)
        return self._llm_fail_count >= 3

    def _llm_ok(self):
        """LLM 调用成功，重置失败计数。"""
        self._llm_fail_count = 0

    def _llm_healthy(self) -> bool:
        """本轮是否仍允许继续调 LLM（熔断后返回 False）。"""
        return self._llm_fail_count < 3

    def refresh_client(self):
        """按当前 config 的 ai_provider 重建 LLM 客户端（设置切换后生效）。"""
        from .llm import build_llm_client
        cfg = self.store.get_config()
        provider = cfg.get("ai_provider", "deepseek")
        # provider 或对应 key 变化才重建
        sig = provider + "|" + (
            cfg.get("gemini_api_key", "") if provider == "gemini" else cfg.get("api_key", "")
        )
        if sig != self._last_provider:
            self.llm = build_llm_client(cfg)
            self._last_provider = sig

    def run_daily(self, target_date: str | None = None, progress=None) -> dict:
        """跑一天：抓新闻 + 生成话题卡 + 搜集语段。target_date 默认今天；非今天只做话题卡和语段。"""
        self.refresh_client()
        if self._running:
            return {"ok": False, "error": "已有流水线正在运行"}
        self._running = True
        target = target_date or today_str()
        cfg = self.store.get_config()
        result = {"date": target, "hotspots": 0, "cards": 0, "phrases": 0,
                  "expressions": 0, "cases": 0, "errors": []}
        # 已存在内容（用于去重，避免同日重复生成）
        existing_hot_titles = {it.get("title", "") for it in self.store.list_all("hotspots")}
        existing_card_topics = {it.get("topic", "") for it in self.store.list_all("topic_cards")}
        # 当天已生成的卡片主题（同日不重复，次日重新生成）
        existing_card_themes = {it.get("theme", "") for it in self.store.list_all("topic_cards")
                                if it.get("date") == target}
        # 进度状态：前端轮询用
        self.store.set_pipeline_status(state="running", step="开始", message="流水线启动", done=0, total=6)
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
                    self._report(step="1/6 热点挑选", message=f"候选新闻 {len(fresh_cands)} 条，AI 挑选重点…",
                                 progress=progress)
                    picked = self._pick_hotspots(fresh_cands, cfg.get("daily_hotspots", 5))
                    if not picked and fresh_cands:
                        # AI 挑选失败（无 key/超时）→ 降级：按最新日期取前 N 条
                        picked = fresh_cands[: cfg.get("daily_hotspots", 5)]
                        result["errors"].append("AI 挑选失败，已降级按最新新闻取前几条")
                    picked_n = len(picked)
                    for idx, item in enumerate(picked, 1):
                        if item["title"] in existing_hot_titles:
                            continue
                        existing_hot_titles.add(item["title"])
                        self._report(step="1/6 热点分析", message=f"分析热点 {idx}/{picked_n}：{item['title'][:15]}…",
                                     done=idx, total=picked_n, progress=progress)
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
                            self._llm_ok()
                        except LLMError as e:
                            result["errors"].append(f"热点分析失败（{item['title'][:15]}…）：{e}")
                            if self._llm_failed(e):
                                result["stopped_reason"] = "api_failed"
                                self._report(step="⚠️ API 不可用", message=f"API 连续失败：{e}",
                                             state="stopped", progress=progress)
                                break  # 熔断：停止剩余热点分析
                else:
                    result["errors"].append("新闻抓取失败或无近14天新闻，已跳过热点生成（可手动录入）")
            else:
                log.info("补拉日 %s：只生成话题卡和语段", target)

            # 2) 话题卡：主题轮转（该主题已有卡则跳过，避免同日重复）
            count = cfg.get("daily_cards", 5)
            themes = self._pick_themes(count, target)
            for t_idx, theme in enumerate(themes, 1):
                self._report(step="2/6 话题卡", message=f"生成话题卡 {t_idx}/{len(themes)}：{theme}…",
                             done=t_idx, total=len(themes), progress=progress)
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
                    self._llm_ok()
                except LLMError as e:
                    result["errors"].append(f"话题卡生成失败（{theme}）：{e}")
                    if self._llm_failed(e):
                        result["stopped_reason"] = "api_failed"
                        self._report(step="⚠️ API 不可用", message=f"API 连续失败：{e}",
                                     state="stopped", progress=progress)
                        break  # 熔断：停止剩余话题卡

            # 3) 语段搜集：素材页 → AI 改稿 → 去重 → 草稿
            phrase_count = cfg.get("daily_phrases", 3)
            if phrase_count > 0 and self._llm_healthy():
                self._report(step="3/6 语段搜集", message="开始搜集语段素材…", progress=progress)
                try:
                    result["phrases"] = self._collect_phrases(
                        cfg.get("phrase_sources", []), phrase_count, progress)
                except Exception as e:  # noqa: BLE001 —— 语段搜集失败不拖垮整体
                    log.exception("语段搜集异常")
                    result["errors"].append(f"语段搜集失败：{e}")

            # 3.5) 表达搜集：素材页 → AI 提炼 → 去重 → 草稿
            expr_count = cfg.get("daily_expressions", 3)
            if expr_count > 0 and self._llm_healthy():
                self._report(step="4/6 表达提炼", message="开始提炼表达…", progress=progress)
                try:
                    result["expressions"] = self._collect_expressions(
                        cfg.get("expr_sources", []), expr_count, progress)
                except Exception as e:  # noqa: BLE001
                    log.exception("表达搜集异常")
                    result["errors"].append(f"表达搜集失败：{e}")

            # 3.6) 案例搜集：素材页 → AI 拆解 → 去重 → 草稿
            case_count = cfg.get("daily_cases", 2)
            if case_count > 0 and self._llm_healthy():
                self._report(step="5/6 案例拆解", message="开始拆解案例…", progress=progress)
                try:
                    result["cases"] = self._collect_cases(
                        cfg.get("phrase_sources", []), case_count, progress)
                except Exception as e:  # noqa: BLE001
                    log.exception("案例搜集异常")
                    result["errors"].append(f"案例搜集失败：{e}")

            # 4) 范文轮转：每天一篇（仅当天）
            if target == today_str() and self._llm_healthy():
                self._report(step="6/6 范文解析", message="解析本地范文…", progress=progress)
                self._maybe_fetch_fanwen(cfg, progress, result)

            # 5) 更新 last_update_date：只有真正生成了内容才推进，
            #    否则启动补拉机制会误以为当天已更新而跳过。
            if (result["hotspots"] + result["cards"] + result["phrases"]
                    + result["expressions"] + result["cases"]) > 0:
                cfg = self.store.get_config()
                if not cfg["last_update_date"] or cfg["last_update_date"] < target:
                    self.store.set_config({"last_update_date": target})
            result["ok"] = not result["errors"] or (
                result["hotspots"] + result["cards"] + result["phrases"]
                + result["expressions"] + result["cases"]) > 0
            return result
        finally:
            self._running = False
            self._llm_fail_count = 0  # 本轮结束重置熔断计数
            # 最终状态：被熔断停止则保留 stopped，否则完成
            if result.get("stopped_reason"):
                pass  # 已在熔断点写入 stopped 状态
            elif result["ok"] and not result.get("errors"):
                self.store.set_pipeline_status(state="done", step="完成",
                                               message=f"生成完成：热点{result['hotspots']} 卡{result['cards']} 语段{result['phrases']}",
                                               done=6, total=6)
            elif result.get("errors") and (result["hotspots"] + result["cards"] +
                                           result["phrases"] + result["expressions"] + result["cases"]) > 0:
                self.store.set_pipeline_status(state="partial", step="部分完成",
                                               message="部分任务完成，部分失败（见日志）", done=6, total=6)
            else:
                self.store.set_pipeline_status(state="failed", step="失败",
                                               message="；".join(result.get("errors", ["未知错误"])[:2]),
                                               done=0, total=6)

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
                    self._llm_ok()
                except LLMError as e:
                    # LLM 失败：若连续失败达 3 次则熔断，停止剩余候选（避免对
                    # 每个候选反复重试拖垮整轮流水线）
                    log.warning("语段改稿失败: %s", e)
                    if self._llm_failed(e):
                        result = self.store.get_config()
                        log.error("LLM 连续失败，熔断语段搜集")
                        return added
        return added

    def _collect_expressions(self, sources: list[dict], limit: int, progress=None) -> int:
        """素材页 → AI 提炼表达词 → 去重 → 草稿。返回新增条数。"""
        if not self.llm.configured:
            log.warning("未配置 API Key，跳过表达搜集")
            return 0
        existing = {e.get("text", "") for e in self.store.list_all("expressions")}
        added = 0
        for source in sources:
            if added >= limit:
                break
            try:
                candidates = fetchers.fetch_phrase_source(source)
            except Exception as e:  # noqa: BLE001
                log.warning("表达素材页抓取失败 %s: %s", source.get("name"), e)
                continue
            for cand in candidates:
                if added >= limit:
                    break
                if progress:
                    progress(f"表达提炼：{cand[:15]}…")
                try:
                    exprs = self.llm.extract_expressions(cand)
                except LLMError as e:
                    log.warning("表达提炼失败: %s", e)
                    if self._llm_failed(e):
                        log.error("LLM 连续失败，熔断表达搜集")
                        return added
                    continue
                for ex in exprs:
                    if added >= limit:
                        break
                    if not ex.get("text") or ex["text"] in existing:
                        continue
                    existing.add(ex["text"])
                    self.store.create("expressions", {
                        "date": today_str(),
                        "status": "草稿",
                        **ex,
                        "collected": False,
                    })
                    added += 1
                    self._llm_ok()
        return added

    def _collect_cases(self, sources: list[dict], limit: int, progress=None) -> int:
        """素材页 → AI 拆解案例 → 去重 → 草稿。返回新增条数。"""
        if not self.llm.configured:
            log.warning("未配置 API Key，跳过案例搜集")
            return 0
        existing = {c.get("title", "") for c in self.store.list_all("cases")}
        added = 0
        for source in sources:
            if added >= limit:
                break
            try:
                candidates = fetchers.fetch_phrase_source(source)
            except Exception as e:  # noqa: BLE001
                log.warning("案例素材页抓取失败 %s: %s", source.get("name"), e)
                continue
            for cand in candidates:
                if added >= limit:
                    break
                if progress:
                    progress(f"案例拆解：{cand[:15]}…")
                try:
                    case = self.llm.decompose_case(cand)
                except LLMError as e:
                    log.warning("案例拆解失败: %s", e)
                    if self._llm_failed(e):
                        log.error("LLM 连续失败，熔断案例搜集")
                        return added
                    continue
                if not case.get("title") or case["title"] in existing:
                    continue
                existing.add(case["title"])
                self.store.create("cases", {
                    "date": today_str(),
                    "status": "草稿",
                    "description": cand,
                    **case,
                })
                added += 1
                self._llm_ok()
        return added

    def _resolve_fanwen_from_file(self, path: str, title: str = "") -> dict:
        """手动/自动解析一个本地范文文件为模板。"""
        from .docreader import read_file_text
        content = read_file_text(path)
        tpl = self.llm.parse_fanwen_template(title or path, content)
        template = self.store.create("templates", {
            "title": tpl.get("title", title or path),
            "source": path,
            "date": today_str(),
            "theme": tpl.get("theme", []),
            "structure": tpl.get("structure", []),
            "killer_sentences": tpl.get("killer_sentences", []),
        })
        return template

    def _parse_next_fanwen(self, cfg: dict, progress=None, result: dict | None = None) -> int:
        """本地范文轮转：扫描 sucai 重建索引 → 解析下一篇待解析范文 → 标记已解析。

        返回本次解析篇数（0 或 1）。
        """
        if not self.llm.configured:
            return 0
        from . import docreader
        sucai_dir = str(_sucai_dir())
        try:
            articles = docreader.scan_sucai(sucai_dir)
        except Exception as e:  # noqa: BLE001
            log.warning("扫描 sucai 失败: %s", e)
            return 0
        # 短篇自动跳过
        for a in articles:
            if len(a.get("content", "")) < docreader.MIN_FANWEN_LEN:
                a["status"] = "已跳过"
        self.store.save_fanwen_index(articles)
        nxt = self.store.next_fanwen_pending()
        if nxt is None:
            if result is not None:
                result["fanwen_note"] = "所有范文已解析，等待新增文件"
            return 0
        if progress:
            progress(f"解析范文：{nxt.get('title', '')[:20]}…")
        try:
            tpl = self.llm.parse_fanwen_template(
                nxt.get("title", ""), nxt.get("content", "")[:3000])
            self.store.create("templates", {
                "title": tpl.get("title", nxt.get("title", "")),
                "source": nxt.get("path", ""),
                "date": today_str(),
                "theme": tpl.get("theme", []),
                "structure": tpl.get("structure", []),
                "killer_sentences": tpl.get("killer_sentences", []),
            })
            self.store.mark_fanwen_status(nxt["id"], "已解析")
            if result is not None:
                result["fanwen_resolved"] = nxt.get("title", "")
            log.info("范文已解析: %s", nxt.get("title", ""))
            self._llm_ok()
            return 1
        except LLMError as e:
            log.warning("范文解析失败: %s", e)
            self._llm_failed(e)
            # 解析失败不标记已解析，下次重试（但防止死循环：本次失败就跳过本轮）
            if result is not None:
                result["errors"].append(f"范文解析失败：{e}")
            return 0

    def _maybe_fetch_fanwen(self, cfg: dict, progress=None, result: dict | None = None):
        """本地轮转解析（每天一篇，随流水线触发）。"""
        self._parse_next_fanwen(cfg, progress, result)

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
