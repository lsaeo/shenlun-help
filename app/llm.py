"""DeepSeek LLM 客户端（OpenAI 兼容格式）。

两个生成任务：
  1. analyze_hotspot(news_item)  -> 结构化考点分析
  2. generate_topic_card(theme)  -> 高频考点话题卡

要求模型返回严格 JSON；解析失败自动重试一次，再失败抛错由调用方兜底。
"""
from __future__ import annotations

import json
import re

import httpx

DEFAULT_TIMEOUT = 90.0


class LLMError(Exception):
    pass


def _strip_code_fence(text: str) -> str:
    text = text.strip()
    m = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if m:
        return m.group(1).strip()
    # 容忍模型直接在 JSON 前后加多余说明：截取第一个 { 到最后一个 }
    a, b = text.find("{"), text.rfind("}")
    if a != -1 and b > a:
        return text[a : b + 1]
    return text


class DeepSeekClient:
    def __init__(self, api_key: str, api_base: str, model: str):
        self.api_key = (api_key or "").strip()
        self.api_base = (api_base or "https://api.deepseek.com").rstrip("/")
        self.model = model or "deepseek-chat"

    @property
    def configured(self) -> bool:
        return bool(self.api_key)

    def _chat_json(self, system: str, user: str) -> dict:
        if not self.configured:
            raise LLMError("未配置 API Key，请在「设置」中填写")
        url = f"{self.api_base}/chat/completions"
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": 0.7,
            "response_format": {"type": "json_object"},
        }
        last_err: Exception | None = None
        for attempt in range(2):
            try:
                resp = httpx.post(
                    url,
                    json=payload,
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    timeout=DEFAULT_TIMEOUT,
                )
                resp.raise_for_status()
                content = resp.json()["choices"][0]["message"]["content"]
                return json.loads(_strip_code_fence(content))
            except Exception as e:  # noqa: BLE001 —— 网络/JSON 错误统一重试一次
                last_err = e
        raise LLMError(f"LLM 调用失败: {last_err}")

    # ---------- 任务 1：热点考点分析 ----------

    HOTSPOT_SYSTEM = (
        "你是一名资深的公务员考试申论教研专家，擅长把时事新闻转化为申论考点。"
        "只输出严格 JSON，不要输出任何多余文字。JSON 字段固定为："
        '{"重点提炼": string数组, "可背金句": string, "意义": string, "角度": string数组, '
        '"对策": string数组, "金句": string, "angles": string数组}。'
        "要求："
        "重点提炼 3~5 条，每条一句话概括这条新闻最核心、最可能考的内容（考生直接背这几点）；"
        "可背金句 1 句，是可直接背诵的一句话（不超过 40 字，有气势、能用于作文）；"
        "意义 60~120 字，说明该事件为何重要、能对应申论哪类主题；"
        "角度 3~4 个，每个是一句独立的论述切入点（如「以民生温度检验治理精度」）；"
        "对策 3~4 条，每条一句话、具体可操作；金句 1 句，气势佳、可用于排比或引用；"
        "angles 3~5 个，这条素材可以挂靠的申论论点/主题方向（如「共建共治共享」「创新社会治理」"
        "「民生服务」「数字政府」），供写作时对号入座。"
        "禁止编造领导人讲话原文，金句必须是原创或公共表述。"
    )

    def analyze_hotspot(self, title: str, summary: str, source: str = "") -> dict:
        user = (
            f"请分析这条新闻并生成申论考点材料。\n"
            f"来源：{source or '未知'}\n标题：{title}\n"
            f"摘要：{summary or '（无摘要，请仅依据标题分析，且不要编造具体事实细节）'}"
        )
        data = self._chat_json(self.HOTSPOT_SYSTEM, user)
        return {
            "重点提炼": [str(x).strip() for x in data.get("重点提炼", []) if str(x).strip()],
            "可背金句": str(data.get("可背金句", "")).strip(),
            "意义": str(data.get("意义", "")).strip(),
            "角度": [str(x).strip() for x in data.get("角度", []) if str(x).strip()],
            "对策": [str(x).strip() for x in data.get("对策", []) if str(x).strip()],
            "金句": str(data.get("金句", "")).strip(),
            "angles": [str(x).strip() for x in data.get("angles", []) if str(x).strip()],
        }

    # ---------- 任务 4：AI 挑选今日重点新闻 ----------

    PICK_SYSTEM = (
        "你是一名资深的公务员考试教研专家（同时熟悉申论和行测常识），负责从一批候选新闻中"
        "挑选出最可能成为考公题目的重点新闻。只输出严格 JSON，不要输出任何多余文字。"
        "JSON 字段固定为："
        '{"pick": [{"title": string, "why": string, "subjects": string数组}]}。'
        "要求："
        "1. 从候选新闻中挑选最合适的 5 条（数量精确为 5，候选不足 5 条则全选）；"
        "2. 优先选：与国计民生相关的重大政策、重要会议、社会治理、民生保障、生态文明、"
        "科技创新、法治建设、经济发展等内容；"
        "3. 每条附 why（一句话说明为何适合考公，60 字内）和 subjects（该新闻可能涉及的"
        "考试科目与方向，如「申论-民生保障」「行测-常识」）；"
        "4. 只挑真实存在的新闻标题，绝不编造；若候选列表为空则输出 {\"pick\": []}。"
    )

    def pick_hotspots(self, candidates: list[dict]) -> list[dict]:
        """从候选新闻中挑选重点。candidates: [{title, summary, url, source, date}]。"""
        if not candidates:
            return []
        user = "候选新闻如下（标题|摘要）：\n" + "\n".join(
            f"{i+1}. {c.get('title', '')} | {c.get('summary', '')[:100]}"
            for i, c in enumerate(candidates)
        )
        data = self._chat_json(self.PICK_SYSTEM, user)
        picked = data.get("pick", []) or []
        # 用标题匹配回原候选，保证 url/date/source 正确
        by_title = {c.get("title", ""): c for c in candidates}
        out = []
        for p in picked:
            title = str(p.get("title", "")).strip()
            cand = by_title.get(title)
            if cand is None:
                # 标题可能被 AI 轻微改写，做包含匹配
                for t, c in by_title.items():
                    if t and (t in title or title in t):
                        cand = c
                        break
            if cand is None:
                continue
            out.append({**cand, "why": str(p.get("why", "")).strip(),
                        "subjects": [str(s).strip() for s in p.get("subjects", []) if str(s).strip()]})
        return out

    # ---------- 任务 5：AI 辅助拆解（观察 → 案例素材） ----------

    DECOMPOSE_SYSTEM = (
        "你是一名资深的公务员考试申论教研专家。用户会粘贴一段社会现象/身边小事/新闻的描述，"
        "你需要把它拆解成可用的申论案例素材。只输出严格 JSON，不要输出任何多余文字。"
        "JSON 字段固定为："
        '{"title": string, "background": string, "problems": string数组, '
        '"measures": string数组, "angles": string数组, "theme": string}。'
        "要求："
        "1. title：给这个案例起一个简短标题（15 字内）；"
        "2. background：背景描述 60~120 字；"
        "3. problems：拆出 2~4 个具体问题，从不同角度（如政策执行问题、观念/习惯问题、"
        "配套措施问题），每条一句话；"
        "4. measures：2~4 条对策，每条一句话、具体可操作；"
        "5. angles：3~5 个可挂靠的申论论点（如「共建共治共享」「基层治理」「民生服务」）；"
        "6. theme 只能从这些值中选一个：民生、生态、法治、文化、创新、经济、基层治理、青年担当。"
        "基于用户描述真实拆解，不要编造用户未提及的具体数据。"
    )

    def decompose_case(self, description: str) -> dict:
        user = f"请把下面这段现象描述拆解成申论案例素材：\n{description[:1000]}"
        data = self._chat_json(self.DECOMPOSE_SYSTEM, user)
        return {
            "title": str(data.get("title", "")).strip(),
            "background": str(data.get("background", "")).strip(),
            "problems": [str(x).strip() for x in data.get("problems", []) if str(x).strip()],
            "measures": [str(x).strip() for x in data.get("measures", []) if str(x).strip()],
            "angles": [str(x).strip() for x in data.get("angles", []) if str(x).strip()],
            "theme": str(data.get("theme", "")).strip(),
        }

    # ---------- 任务 3：语段改稿（网络素材 → 标准格式） ----------

    PHRASE_SYSTEM = (
        "你是一名资深的公务员考试申论教研专家，负责把收集到的申论语段素材整理成标准格式。"
        "只输出严格 JSON，不要输出任何多余文字。JSON 字段固定为："
        '{"text": string, "template": string, "examples": string数组, '
        '"position": string数组, "theme": string数组, "technique": string数组, "usage": string}。'
        "要求："
        "1. text：整理后的语段原文，保留原有气势和修辞，去除冗余；"
        "2. template：把 text 中具体内容/主题词替换为 ____（连续4个下划线）挖空，保留句式骨架，"
        "   让考生能套用到其他主题；"
        "3. examples：给出 1~2 个改写例句，演示框架套用到不同主题后的效果；"
        "4. position 只能从这些值中选：开头、结尾、过渡、论证；theme 只能从这些值中选："
        "民生、生态、法治、文化、创新、经济、基层治理、青年担当；"
        "5. technique 从这些值中选（可多选）：排比、对仗、引用、比喻、设问、递进；"
        "6. usage 用一句话说明这条语段适合用在什么场景。"
        "若素材本身就是完整的优秀语段，直接整理；若素材只是碎片，请补全成可用的完整语段。"
    )

    def format_phrase(self, raw_text: str) -> dict:
        """把一条网络搜集的语段素材改写成标准格式（含填空框架+改写例句）。"""
        user = f"请把下面这条申论语段素材整理成标准格式：\n{raw_text[:800]}"
        data = self._chat_json(self.PHRASE_SYSTEM, user)
        return {
            "text": str(data.get("text", "")).strip(),
            "template": str(data.get("template", "")).strip(),
            "examples": [str(x).strip() for x in data.get("examples", []) if str(x).strip()],
            "position": [str(x).strip() for x in data.get("position", []) if str(x).strip()],
            "theme": [str(x).strip() for x in data.get("theme", []) if str(x).strip()],
            "technique": [str(x).strip() for x in data.get("technique", []) if str(x).strip()],
            "usage": str(data.get("usage", "")).strip(),
        }

    # ---------- 任务 2：高频考点话题卡 ----------

    CARD_SYSTEM = (
        "你是一名资深的公务员考试申论教研专家，为考生制作高频考点话题卡。"
        "只输出严格 JSON，不要输出任何多余文字。JSON 字段固定为："
        '{"topic": string, "背景": string, "意义": string, "问题": string, '
        '"对策": string数组, "金句": string, "angles": string数组}。'
        "要求：topic 是简明话题名（如「数字政府建设」）；背景 80~120 字概述政策背景与现状；"
        "意义 60~100 字；问题 60~100 字指出当前短板；对策 3~4 条每条一句话；"
        "金句 1 句可直接用于论证的漂亮表述；angles 3~5 个可挂靠的申论论点"
        "（如「共建共治共享」「数字政府」「基层治理」）。禁止编造具体数据与领导人讲话原文。"
    )

    def generate_topic_card(self, theme: str) -> dict:
        user = f"请围绕申论主题「{theme}」，制作一张高频考点话题卡。"
        data = self._chat_json(self.CARD_SYSTEM, user)
        return {
            "theme": theme,
            "topic": str(data.get("topic", "")).strip(),
            "背景": str(data.get("背景", "")).strip(),
            "意义": str(data.get("意义", "")).strip(),
            "问题": str(data.get("问题", "")).strip(),
            "对策": [str(x).strip() for x in data.get("对策", []) if str(x).strip()],
            "金句": str(data.get("金句", "")).strip(),
            "angles": [str(x).strip() for x in data.get("angles", []) if str(x).strip()],
        }
