# -*- coding: utf-8 -*-
"""测试工具：提供隔离的临时数据目录，避免测试污染用户真实数据。"""
import sys, io, tempfile, shutil, os
sys.path.insert(0, ".")

PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SEED = os.path.join(PROJECT, "seed")


class TmpData:
    """创建一个临时 data 目录（从 seed 初始化），随用随删。"""

    def __init__(self):
        self.dir = tempfile.mkdtemp(prefix="shenlun_test_")

    def path(self, *parts):
        return os.path.join(self.dir, *parts)

    def cleanup(self):
        shutil.rmtree(self.dir, ignore_errors=True)
