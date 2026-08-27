# -*- coding: utf-8 -*-
"""范文候选质量测试：索引页/导航页检测。"""
import sys, io
sys.path.insert(0, ".")
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
from app import fetchers

test_pages = {
    "真题索引": ("历年国考申论真题 2026-04-28 [申论] 2026国考申论真题（地市卷） "
                 "2026-04-28 [申论] 2026国考申论真题（副省卷） 2026-01-05 [申论] 2026国考真题（执法卷） "
                 "2025-08-25 [申论] 2025国考真题 2024-12-01 [申论] 2024国考真题 2023-11-01 [申论] 2023国考真题", True),
    "省份导航": ("各地考试 华东 山东 江苏 浙江 安徽 江西 福建 上海 华中 湖北 湖南 河南 华南 广东 广西 "
                 "海南 西南 四川 云南 贵州 重庆 西藏 西北 陕西 甘肃 宁夏 新疆 青海 华北 北京 天津 内蒙古 "
                 "山西 河北 东北 辽宁 吉林 黑龙江 更多 村官 选调生 乡镇公务员 事业单位 特岗教师", True),
    "真实范文": ("近年来，电信网络诈骗案件多发，人民群众财产安全受到威胁。守护好群众的钱袋子，"
                 "既是民生所系，也是治理所需。守护钱袋子，要在宣传上做加法。要创新反诈宣传形式，"
                 "用群众听得懂的语言，让反诈知识入脑入心。守护钱袋子，要在防范上做乘法。要筑牢技术防线，"
                 "及时预警拦截可疑交易。守护钱袋子，要在打击上做减法。要保持高压态势，从严从快打击犯罪。"
                 "利民之事，丝发必兴。唯有宣传加力、防范加码、打击加严，方能守好群众的钱袋子。", False),
    "空文本": ("", True),
}

ok = True
for name, (text, expect_index) in test_pages.items():
    got = fetchers._is_index_page(text)
    status = "PASS" if got == expect_index else "FAIL"
    if got != expect_index:
        ok = False
    print(f"{status} {name}: {'索引页' if got else '正文'} (期望 {'索引页' if expect_index else '正文'})")

print("\n=== FANWEN QUALITY TEST", "PASSED" if ok else "FAILED", "===")
sys.exit(0 if ok else 1)
