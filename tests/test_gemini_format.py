# -*- coding: utf-8 -*-
"""Gemini 客户端格式适配测试：请求/响应转换层。"""
import sys, io
sys.path.insert(0, ".")
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
from app.llm import GeminiClient, DeepSeekClient, BaseLLMClient, LLMError, build_llm_client
import json


class FakeGeminiResponse:
    """模拟 Gemini HTTP 响应。"""
    def __init__(self, body, status=200, content_type="application/json"):
        self._body = body
        self.status_code = status
        self.headers = {"content-type": content_type}
    def json(self):
        return self._body


class FakeGeminiTransport(GeminiClient):
    """捕获请求，返回固定响应。"""
    def __init__(self, responses, api_key="AIza-test"):
        super().__init__(api_key, "gemini-2.0-flash")
        self.responses = list(responses)
        self.captured = []

    def _chat_json(self, system, user):
        if not self.responses:
            raise LLMError("模拟无响应")
        resp = self.responses.pop(0)
        self.captured.append({"system": system, "user": user, "status": resp.status_code, "body": resp._body})
        if resp.status_code != 200:
            body = resp.json()
            err = body.get("error", {}).get("message", "")
            raise LLMError(f"Gemini 调用失败 HTTP {resp.status_code}: {err}")
        candidates = resp.json().get("candidates", [])
        if not candidates:
            raise LLMError("Gemini 响应为空（无 candidates）")
        parts = candidates[0].get("content", {}).get("parts", [])
        if not parts:
            raise LLMError("Gemini 响应为空（无 parts）")
        text = parts[0].get("text", "")
        from app.llm import _json_from_text
        return _json_from_text(text)


# 1) 正常响应解析（含 markdown code fence）
ok_body = {"candidates": [{"content": {"parts": [{"text": '```json\n{"重点提炼": ["a"], "金句": "金句"}\n```'}]}}]}
client = FakeGeminiTransport([FakeGeminiResponse(ok_body)])
r = client.analyze_hotspot("标题", "摘要", "来源")
assert r["重点提炼"] == ["a"] and r["金句"] == "金句", r
print("[OK] Gemini 正常响应 → 统一 JSON 结构（与 DeepSeek 一致）")

# 2) HTTP 错误带原因
err_body = {"error": {"message": "API key not valid. Please pass a valid API key."}}
client2 = FakeGeminiTransport([FakeGeminiResponse(err_body, status=400)])
try:
    client2.analyze_hotspot("t", "s")
    assert False, "应抛错"
except LLMError as e:
    assert "400" in str(e) and "API key" in str(e), str(e)
    print(f"[OK] HTTP 错误带原因: {e}")

# 3) 空 candidates
client3 = FakeGeminiTransport([FakeGeminiResponse({"candidates": []})])
try:
    client3.analyze_hotspot("t", "s")
    assert False
except LLMError as e:
    assert "candidates" in str(e)
    print(f"[OK] 空响应报错: {e}")

# 4) 无 key
client4 = GeminiClient("")
assert not client4.configured
try:
    client4.analyze_hotspot("t", "s")
    assert False
except LLMError as e:
    assert "Gemini API Key" in str(e)
    print(f"[OK] 无 key 报错: {e}")

# 5) build_llm_client 按 provider 构建
ds = build_llm_client({"ai_provider": "deepseek", "api_key": "k", "model": "m"})
gm = build_llm_client({"ai_provider": "gemini", "gemini_api_key": "g", "gemini_model": "gm"})
assert isinstance(ds, DeepSeekClient)
assert isinstance(gm, GeminiClient)
assert gm.model == "gm"
print("[OK] build_llm_client 按 provider 切换")

print("\n=== GEMINI FORMAT TEST PASSED ===")
