# -*- coding: utf-8 -*-
"""熔断机制测试：LLM 连续失败后停止剩余候选，不逐个重试。"""
import sys, io
sys.path.insert(0, ".")
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
from _util import TmpData, SEED
from app.store import JsonStore
from app.pipeline import Pipeline
from app.llm import LLMError


class FlakyLLM:
    """模拟 LLM：一直失败。"""
    configured = True
    calls = 0

    def format_phrase(self, raw_text):
        self.calls += 1
        raise LLMError("连接被重置 [WinError 10054]")


tmp = TmpData()
try:
    store = JsonStore(tmp.dir, SEED)
    flaky = FlakyLLM()
    pipe = Pipeline(store, flaky)

    # 模拟多候选语段素材（3 个源 × 各若干候选）
    import app.pipeline as pipeline_mod
    orig = pipeline_mod.fetchers.fetch_phrase_source
    pipeline_mod.fetchers.fetch_phrase_source = lambda source: [
        "候选一内容足够长用于测试。", "候选二内容足够长用于测试。",
        "候选三内容足够长用于测试。", "候选四内容足够长用于测试。"]

    n = pipe._collect_phrases([{"name": "测试源", "url": "x"}], 3)
    print(f"新增语段: {n} | LLM 调用次数: {flaky.calls}")

    # 熔断应在第 3 次失败后停止（不再对第 4 个候选调用）
    assert flaky.calls <= 3, f"LLM 应熔断于 3 次, 实际调用 {flaky.calls} 次"
    print(f"[OK] LLM 连续失败熔断: 仅调用 {flaky.calls} 次（修复前会对所有候选重试）")
finally:
    tmp.cleanup()
print("\n=== CIRCUIT BREAKER TEST PASSED ===")
