# -*- coding: utf-8 -*-
"""测试脚本 —— 覆盖所有可离线测试的纯逻辑函数。"""
import json
import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

passed = 0
failed = 0


def check(name, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
        print(f"  ✅ {name}")
    else:
        failed += 1
        print(f"  ❌ {name}  {detail}")


# ================================================================ config.py
print("\n" + "=" * 60)
print("config.py")
print("=" * 60)

from config import DEFAULT_CONFIG, load_config, save_config, _normalize_times

# --- _normalize_times ---
cfg = {"time": {"times": ["3:43", "03:43", "10:00"]}}
result = _normalize_times(cfg)
check("规范化 3:43→03:43 并去重", result["time"]["times"] == ["03:43", "10:00"],
      f"got {result['time']['times']}")

cfg = {"time": {"times": ["0:05", "00:05", "23:59", "0:00"]}}
result = _normalize_times(cfg)
check("规范化 0:05→00:05, 0:00→00:00", result["time"]["times"] == ["00:00", "00:05", "23:59"],
      f"got {result['time']['times']}")

cfg = {"time": {"times": []}}
result = _normalize_times(cfg)
check("空列表不动", result["time"]["times"] == [])

cfg = {"time": {"times": ["abc", "25:00", "12:34"]}}
result = _normalize_times(cfg)
check("无效时间保持原样", result["time"]["times"] == ["12:34", "25:00", "abc"],
      f"got {result['time']['times']}")

cfg = {"time": {}}  # no times key
result = _normalize_times(cfg)
check("无 times 键不崩溃", True)

# --- load_config ---
# 不干扰真实配置，用临时文件测 _merge 和 _normalize_times 的逻辑
cfg = DEFAULT_CONFIG.copy()
check("默认配置含 monitor_interval_sec", cfg["runtime"].get("monitor_interval_sec") == 60)
check("默认配置有 api/contract/time/pause/runtime 五个顶级键",
      set(cfg.keys()) >= {"api", "contract", "time", "pause", "runtime"})


# ================================================================ stats.py
print("\n" + "=" * 60)
print("stats.py")
print("=" * 60)

from stats import StatsTracker

# 用临时文件隔离
with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
    tmp_stats = f.name

# --- 空文件（首次运行）---
if os.path.exists(tmp_stats):
    os.remove(tmp_stats)
st = StatsTracker()
st._sessions = []
st._current = None
check("空记录 summary 不崩溃", "暂无定投记录" in st.summary())

# --- 含旧数据（没有 paused 字段）---
old_data = [{
    "start_time": "2026-08-06 10:00",
    "end_time": "2026-08-06 11:00",
    "contract": "BTC-USDT-SWAP",
    "side": "sell",
    "success": 3,
    "skipped": 1,
    "failed": 0,
    "unfilled": 2,
}]
st._sessions = old_data
summary = st.summary()
check("旧数据（无paused）不崩溃", "BTC-USDT-SWAP" in summary, f"summary: {summary[:200]}")
check("旧数据 paused 显示为 0", "暂停错过 0" in summary, f"summary: {summary[:200]}")
check("旧数据共 6 次定投", "共 6 次" in summary)

# --- 含 paused 的新数据 ---
new_data = [{
    "start_time": "2026-08-07 18:00",
    "end_time": None,
    "contract": "XAU-USDT-SWAP",
    "side": "sell",
    "success": 5,
    "skipped": 0,
    "failed": 1,
    "unfilled": 0,
    "paused": 2,
}]
st._sessions = new_data
summary = st.summary()
check("新数据 paused=2 显示正确", "暂停错过 2" in summary)
check("新数据共 8 次", "共 8 次" in summary)

# --- 混合新旧数据 ---
st._sessions = old_data + new_data
summary = st.summary()
check("混合数据不崩溃", "BTC-USDT-SWAP" in summary and "XAU-USDT-SWAP" in summary)
check("混合累计 paused=2", "暂停错过 2" in summary)

# --- start / count / end ---
st._sessions = []
st._current = None
st.start_session("ETH-USDT-SWAP", "buy")
st.count_success()
st.count_success()
st.count_skipped()
st.count_failed()
st.count_unfilled()
st.count_paused()
st.count_paused()
st.end_session()
check("start+count+end 完整流程", len(st._sessions) == 1)
s = st._sessions[0]
check("计数正确", s["success"] == 2 and s["skipped"] == 1 and s["failed"] == 1
      and s["unfilled"] == 1 and s["paused"] == 2,
      f"got success={s['success']} skipped={s['skipped']} failed={s['failed']} unfilled={s['unfilled']} paused={s['paused']}")

# 清理
if os.path.exists(tmp_stats):
    os.remove(tmp_stats)


# ================================================================ okx_bot.py 纯函数
print("\n" + "=" * 60)
print("okx_bot.py (pure logic)")
print("=" * 60)

from okx_bot import OKXClient

# 构造最小 OKXClient 实例（不联网，只测纯函数）
dummy = OKXClient(
    api_key="dummy", secret_key="dummy", passphrase="dummy",
    flag="1", timezone="Asia/Shanghai",
)

# --- _norm_hm ---
check("_norm_hm 3:43→03:43", dummy._norm_hm("3:43") == "03:43")
check("_norm_hm 03:43 不变", dummy._norm_hm("03:43") == "03:43")
check("_norm_hm 0:00→00:00", dummy._norm_hm("0:00") == "00:00")
check("_norm_hm 23:59 不变", dummy._norm_hm("23:59") == "23:59")
check("_norm_hm 空字符串兜底", dummy._norm_hm("") == "")
check("_norm_hm 垃圾兜底", dummy._norm_hm("abc") == "abc")
check("_norm_hm None 兜底", dummy._norm_hm(None) == "None")

# --- _parse_date ---
check("_parse_date 正常", dummy._parse_date("2026-08-07") == datetime(2026, 8, 7).date())
check("_parse_date None", dummy._parse_date(None) is None)
check("_parse_date 空", dummy._parse_date("") is None)
check("_parse_date 垃圾", dummy._parse_date("abc") is None)
check("_parse_date 假日期", dummy._parse_date("2026-13-40") is None)

# --- _date_valid ---
from datetime import date

cfg_t = {
    "time": {
        "start_date": "2026-08-01",
        "end_date": "2026-08-31",
        "date_type": "everyday",
    }
}
now_ok = datetime(2026, 8, 7, 12, 0, tzinfo=dummy.tz)
now_before = datetime(2026, 7, 30, 12, 0, tzinfo=dummy.tz)
now_after = datetime(2026, 9, 5, 12, 0, tzinfo=dummy.tz)
now_sat = datetime(2026, 8, 8, 12, 0, tzinfo=dummy.tz)     # 周六
now_sun = datetime(2026, 8, 9, 12, 0, tzinfo=dummy.tz)     # 周日
now_mon = datetime(2026, 8, 10, 12, 0, tzinfo=dummy.tz)    # 周一

check("everyday 有效日期", dummy._date_valid(now_ok, cfg_t))
check("everyday 日期前", not dummy._date_valid(now_before, cfg_t))
check("everyday 日期后", not dummy._date_valid(now_after, cfg_t))

cfg_t["time"]["date_type"] = "weekday"
check("weekday 周一有效", dummy._date_valid(now_mon, cfg_t))
check("weekday 周六无效", not dummy._date_valid(now_sat, cfg_t))
check("weekday 周日无效", not dummy._date_valid(now_sun, cfg_t))

# --- _current_slot ---
cfg_slot = {"time": {"times": ["10:00", "14:30", "3:43"]}}
now_match = datetime(2026, 8, 7, 10, 0, 15, tzinfo=dummy.tz)        # 10:00:15
now_nomatch = datetime(2026, 8, 7, 10, 1, 0, tzinfo=dummy.tz)       # 10:01:00
now_match2 = datetime(2026, 8, 7, 3, 43, 55, tzinfo=dummy.tz)       # 03:43:55

check("_current_slot 匹配 10:00", dummy._current_slot(now_match, cfg_slot) == "2026-08-07 10:00")
check("_current_slot 匹配 3:43→03:43", dummy._current_slot(now_match2, cfg_slot) == "2026-08-07 03:43")
check("_current_slot 不匹配 10:01", dummy._current_slot(now_nomatch, cfg_slot) is None)

# --- _missed_slots ---
done_set = set()
now_late = datetime(2026, 8, 7, 15, 0, 0, tzinfo=dummy.tz)
missed = dummy._missed_slots(now_late, cfg_slot, done_set)
check("_missed_slots 10:00 错过", any("10:00" in m for m in missed), f"got {missed}")
check("_missed_slots 14:30 错过", any("14:30" in m for m in missed), f"got {missed}")
check("_missed_slots 03:43 错过", any("03:43" in m for m in missed), f"got {missed}")
check("_missed_slots 返回 3 个", len(missed) == 3, f"got {len(missed)}")

# 标记一个已执行
done_set.add("2026-08-07 10:00")
missed2 = dummy._missed_slots(now_late, cfg_slot, done_set)
check("_missed_slots 已执行的跳过", len(missed2) == 2, f"got {len(missed2)}")

# 还没到的时间不列
now_early = datetime(2026, 8, 7, 9, 0, 0, tzinfo=dummy.tz)
missed3 = dummy._missed_slots(now_early, cfg_slot, set())
check("_missed_slots 未到时间不列", len(missed3) == 1, f"should only have 03:43, got {missed3}")

# since 参数：只返回暂停开始之后的 slot
pause_start = datetime(2026, 8, 7, 11, 0, 0, tzinfo=dummy.tz)
missed4 = dummy._missed_slots(now_late, cfg_slot, set(), since=pause_start)
check("_missed_slots since=11:00 只返回 14:30", len(missed4) == 1 and "14:30" in missed4[0],
      f"got {missed4}")

# --- _fmt_sz ---
check("_fmt_sz 整数", OKXClient._fmt_sz(1.0) == "1")
check("_fmt_sz 小数", OKXClient._fmt_sz(1.5) == "1.5")
check("_fmt_sz 零", OKXClient._fmt_sz(0.0) == "0")
check("_fmt_sz 大数", OKXClient._fmt_sz(123.456) == "123.456")
check("_fmt_sz 尾零去除", OKXClient._fmt_sz(1.2000000000) == "1.2")

# --- amount_to_contracts ---
# ct_val=0.001 (XAU), lot_sz=1
n = dummy.amount_to_contracts(1000, 4300, 0.001, 1)
check("1000USDT at 4300 XAU 约 232 张", 230 <= n <= 235, f"got {n}")

# ct_val=0.01 (BTC), lot_sz=0.01
n = dummy.amount_to_contracts(100, 50000, 0.01, 0.01)
check("100USDT at 50000 BTC 约 0.2 张", 0.19 <= n <= 0.21, f"got {n}")

# 金额不够最小量
n = dummy.amount_to_contracts(1, 4300, 0.001, 1)
check("1USDT at 4300 XAU = 0 张", n == 0.0)

# 零价保护
n = dummy.amount_to_contracts(100, 0, 0.001, 1)
check("价格为零返回 0", n == 0.0)

# --- _target_reached ---
check("做空 mark≤target 到达", dummy._target_reached(3300, 3400, "sell"))
check("做空 mark>target 未到达", not dummy._target_reached(3500, 3400, "sell"))
check("做多 mark≥target 到达", dummy._target_reached(3500, 3400, "buy"))
check("做多 mark<target 未到达", not dummy._target_reached(3300, 3400, "buy"))
check("target=None 不触发", not dummy._target_reached(100, None, "sell"))


# ================================================================ menu.py
print("\n" + "=" * 60)
print("menu.py")
print("=" * 60)

from menu import _normalize as menu_normalize

result = menu_normalize([("选项A", "a"), ("选项B", "b")])
check("二元组列表不变", result == [("选项A", "a"), ("选项B", "b")])

result = menu_normalize(["苹果", "香蕉"])
check("字符串列表转为同值二元组", result == [("苹果", "苹果"), ("香蕉", "香蕉")])

result = menu_normalize([])
check("空列表", result == [])

result = menu_normalize([("A", 1), ("B", 2)])
check("二元组 value 保持原类型", result == [("A", 1), ("B", 2)])


# ================================================================ notifier.py
print("\n" + "=" * 60)
print("notifier.py")
print("=" * 60)

from notifier import Notifier

n = Notifier({"channel": "none", "enabled": True})
check("channel=none 不启用", not n.enabled)

n = Notifier({"channel": "bark", "enabled": False})
check("enabled=False 不启用", not n.enabled)

n = Notifier({"channel": "bark", "enabled": True, "bark_url": "https://api.day.app/test"})
check("bark 启用", n.enabled)

# send 不崩溃（网络不通只记日志）
try:
    n.send("测试标题", "测试内容")
    check("send 不崩溃（无网络）", True)
except Exception as e:
    check("send 不崩溃（无网络）", False, str(e))

# test 返回错误信息（无有效渠道配置）
n2 = Notifier({"channel": "none"})
ok, msg = n2.test()
check("none 渠道 test 返回 False", not ok)
check("none 渠道 test 有说明", len(msg) > 0)


# ================================================================ config.py 边界
print("\n" + "=" * 60)
print("config.py (edge cases)")
print("=" * 60)

# _normalize_times 不会产生重复
cfg = {"time": {"times": ["03:43", "3:43", "3:43", "03:43"]}}
result = _normalize_times(cfg)
check("重复 3:43/03:43 只保留一个", result["time"]["times"] == ["03:43"],
      f"got {result['time']['times']}")

# _normalize_times 排序
cfg = {"time": {"times": ["23:00", "01:00", "12:00"]}}
result = _normalize_times(cfg)
check("时间排序", result["time"]["times"] == ["01:00", "12:00", "23:00"],
      f"got {result['time']['times']}")


# ================================================================ 结果
print("\n" + "=" * 60)
total = passed + failed
print(f"  通过: {passed}/{total}")
if failed > 0:
    print(f"  ❌ 失败: {failed}")
    sys.exit(1)
else:
    print(f"  ✅ 全部通过！")
