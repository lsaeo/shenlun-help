# -*- coding: utf-8 -*-
"""模型名迁移测试：旧 deepseek-chat/deepseek-reasoner 应自动迁移到 deepseek-v4-flash。"""
import sys, io, os, json, tempfile, shutil
sys.path.insert(0, ".")
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
from app.store import JsonStore, DEFAULT_CONFIG

tmp = tempfile.mkdtemp()
try:
    # 默认值已是新模型
    assert DEFAULT_CONFIG["model"] == "deepseek-v4-flash", f"默认模型应为 v4-flash, 实际 {DEFAULT_CONFIG['model']}"

    for old in ("deepseek-chat", "deepseek-reasoner"):
        os.makedirs(os.path.join(tmp, "data"), exist_ok=True)
        with open(os.path.join(tmp, "data", "config.json"), "w", encoding="utf-8") as f:
            json.dump({"api_key": "sk-test", "model": old}, f)
        store = JsonStore(os.path.join(tmp, "data"), "seed")
        cfg = store.get_config()
        assert cfg["model"] == "deepseek-v4-flash", f"{old} 未迁移, 实际 {cfg['model']}"
        assert cfg["api_key"] == "sk-test", "api_key 应保留"
        print(f"[OK] {old} -> {cfg['model']} (api_key 保留)")
finally:
    shutil.rmtree(tmp, ignore_errors=True)

print("\n=== MODEL MIGRATION TEST PASSED ===")
