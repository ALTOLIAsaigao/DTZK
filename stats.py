# -*- coding: utf-8 -*-
"""
stats.py —— 定投统计模块

记录每段定投策略的执行情况，持久化到 stats.json。
"""
import json
import os
from datetime import datetime

from config import BASE_DIR

STATS_PATH = os.path.join(BASE_DIR, "stats.json")


class StatsTracker:
    """轻量统计器：开始一段定投 → 记录事件 → 结束。"""

    def __init__(self):
        self._current = None
        self._sessions = []
        self._load()

    # ---------------------------------------------------------------- 持久化
    def _load(self):
        if os.path.exists(STATS_PATH):
            try:
                with open(STATS_PATH, "r", encoding="utf-8") as f:
                    self._sessions = json.load(f)
            except (json.JSONDecodeError, OSError):
                self._sessions = []

    def _save(self):
        with open(STATS_PATH, "w", encoding="utf-8") as f:
            json.dump(self._sessions, f, ensure_ascii=False, indent=2)

    # ---------------------------------------------------------------- 会话
    def start_session(self, inst_id, side):
        """开始一段新定投。"""
        self._current = {
            "start_time": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "end_time": None,
            "contract": inst_id,
            "side": side,
            "success": 0,
            "skipped": 0,
            "failed": 0,
            "unfilled": 0,
            "paused": 0,
        }

    def end_session(self):
        """结束当前定投段。"""
        if self._current:
            self._current["end_time"] = datetime.now().strftime("%Y-%m-%d %H:%M")
            self._sessions.append(self._current)
            self._current = None
            self._save()

    # ---------------------------------------------------------------- 计数
    def _inc(self, key):
        if self._current:
            self._current[key] += 1
            self._save()

    def count_success(self):
        self._inc("success")

    def count_skipped(self):
        self._inc("skipped")

    def count_failed(self):
        self._inc("failed")

    def count_unfilled(self):
        self._inc("unfilled")

    def count_paused(self):
        self._inc("paused")

    # ---------------------------------------------------------------- 查看
    def summary(self):
        """返回统计摘要文本。"""
        if not self._sessions:
            return "暂无定投记录。"

        lines = []
        total_success = 0
        total_skipped = 0
        total_failed = 0
        total_unfilled = 0
        total_paused = 0

        lines.append("=" * 56)
        lines.append("定投统计")
        lines.append("=" * 56)

        for i, s in enumerate(self._sessions, 1):
            end = s["end_time"] or "进行中"
            total = s["success"] + s["skipped"] + s["failed"] + s["unfilled"] + s.get("paused", 0)
            lines.append(
                f"\n第{i}段  {s['start_time']} → {end}"
                f"\n  合约: {s['contract']}  {s['side']}"
                f"\n  成功 {s['success']} 次  |  跳过 {s['skipped']} 次"
                f"  |  失败 {s['failed']} 次  |  未成交 {s['unfilled']} 次"
                f"\n  暂停错过 {s.get('paused', 0)} 次"
                f"\n  本段共 {total} 次定投"
            )
            total_success += s["success"]
            total_skipped += s["skipped"]
            total_failed += s["failed"]
            total_unfilled += s["unfilled"]
            total_paused += s.get("paused", 0)

        grand = total_success + total_skipped + total_failed + total_unfilled + total_paused
        lines.append(f"\n{'─' * 56}")
        lines.append(
            f"累计 {len(self._sessions)} 段策略  |  共 {grand} 次定投"
            f"\n  成功 {total_success}  |  跳过 {total_skipped}"
            f"  |  失败 {total_failed}  |  未成交 {total_unfilled}"
            f"\n  暂停错过 {total_paused}"
        )
        lines.append("=" * 56)
        return "\n".join(lines)


# 模块级单例
tracker = StatsTracker()
