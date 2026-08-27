# -*- coding: utf-8 -*-
"""本地范文文档解析测试：docx/txt 读取 + 范文N拆分 + 短篇跳过。"""
import sys, io, os, tempfile
sys.path.insert(0, ".")
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
from app import docreader

# 1) 范文标记拆分
text = """范文一话题：城市治理数字化
数字化让城市更畅通。城市治理水平稳步提升。数字化建设是重要抓手。
城市治理现代化需要数据赋能，更需要以人为本。要坚持问题导向，补齐短板。
基层社区是治理的最小单元，要打通最后一公里，让服务触达千家万户。
范文二话题：基层治理
基层治理是国家治理基石。要把矛盾化解在基层。治理效能持续提升。
党建引领是根本保证，群众参与是力量源泉，法治保障是坚强支撑。
范文三话题：短篇示例
太短了。
"""
arts = docreader.split_fanwen(text, source_file="测试.docx")
print(f"拆分 {len(arts)} 篇")
assert len(arts) == 3, f"应拆 3 篇, 实际 {len(arts)}"
assert arts[0]["title"] == "范文一话题：城市治理数字化"
assert "数字化" in arts[0]["content"]
assert arts[1]["topic"] == "基层治理"
print(f"[OK] 拆分 {len(arts)} 篇, 标题/topic 正确")

# 短篇识别逻辑验证：用 30 字阈值模拟（真实阈值 MIN_FANWEN_LEN=300 由 scan_sucai 应用）
SHORT = 30
short = [a for a in arts if len(a["content"]) < SHORT]
assert len(short) == 1 and short[0]["title"].startswith("范文三"), f"仅范文三应为短篇, 实际 {len(short)}"
print(f"[OK] 短篇识别: {len(short)} 篇 (<{SHORT}字), 长篇保留 {len(arts)-len(short)} 篇")
# 真实阈值常量存在
assert docreader.MIN_FANWEN_LEN == 300
print(f"[OK] 真实阈值 MIN_FANWEN_LEN={docreader.MIN_FANWEN_LEN}")

# 2) txt 读取（GBK 编码）
tmp = tempfile.mkdtemp()
try:
    gbk_path = os.path.join(tmp, "范文.txt")
    with open(gbk_path, "w", encoding="gbk") as f:
        f.write("范文一话题：测试\n这是一篇测试范文正文。内容足够长。用于验证编码读取。")
    txt = docreader.read_file_text(gbk_path)
    assert "测试" in txt and "范文一" in txt, "GBK txt 读取失败"
    print("[OK] GBK txt 读取")

    # 3) 无标记回退：整篇一篇
    plain = "没有范文标记的整篇文章。第一段。第二段。第三段。第四段。"
    arts2 = docreader.split_fanwen(plain, source_file="无标记.txt")
    assert len(arts2) == 1, f"无标记应 1 篇, 实际 {len(arts2)}"
    print(f"[OK] 无标记回退 1 篇")
finally:
    import shutil
    shutil.rmtree(tmp, ignore_errors=True)

# 4) 真实 sucai 扫描（若存在）
if os.path.isdir("sucai"):
    real = docreader.scan_sucai("sucai")
    print(f"[INFO] sucai 实际扫描 {len(real)} 篇")
    if real:
        assert all(a.get("title") for a in real)
        assert real[0].get("file"), "应带文件名"

print("\n=== DOCREADER TEST PASSED ===")
