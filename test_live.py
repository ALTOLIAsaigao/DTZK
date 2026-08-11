# -*- coding: utf-8 -*-
"""在线测试 —— 用模拟盘 API 验证所有可测函数。"""
import json
import os
import sys
import time

import logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("test")

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

def banner(title):
    print("\n" + "=" * 60)
    print(title)
    print("=" * 60)

# ---------------------------------------------------------------- 加载配置
banner("加载配置")
cfg_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")
with open(cfg_path, "r", encoding="utf-8") as f:
    cfg = json.load(f)

api = cfg["api"]
check("API Key 存在", bool(api["api_key"]))
check("模拟盘 flag=1", api["flag"] == "1")
check("合约 = XAU-USDT-SWAP", cfg["contract"]["inst_id"] == "XAU-USDT-SWAP")

# ---------------------------------------------------------------- 构建客户端
banner("test_connection — 登录连接")
from okx_bot import OKXClient

client = OKXClient(
    api_key=api["api_key"],
    secret_key=api["secret_key"],
    passphrase=api["passphrase"],
    flag=api["flag"],
    timezone=cfg["runtime"].get("timezone", "Asia/Shanghai"),
    proxy=cfg["runtime"].get("proxy") or None,
    notify_cfg=cfg.get("notify", {}),
)

ok, res = client.test_connection()
check("登录成功 code=0", ok, f"res={str(res)[:200]}")
if not ok:
    print(f"\n❌ 登录失败，终止测试: {res}")
    sys.exit(1)

inst_id = cfg["contract"]["inst_id"]

# ---------------------------------------------------------------- get_instrument
banner("get_instrument — 合约信息")
inst = client.get_instrument(inst_id)
check("返回非空", inst is not None and len(inst) > 0)
ct_val = float(inst.get("ctVal", 0))
lot_sz = float(inst.get("lotSz", 0))
min_sz = float(inst.get("minSz", lot_sz))
check("面值 > 0", ct_val > 0, f"ctVal={ct_val}")
check("lotSz > 0", lot_sz > 0, f"lotSz={lot_sz}")
print(f"     合约={inst.get('instId')} 面值={ct_val} 最小下单={min_sz} 张  lotSz={lot_sz}")

# ---------------------------------------------------------------- get_ticker
banner("get_ticker — 行情")
ticker = client.get_ticker(inst_id)
check("ticker 非空", ticker is not None)
bid = float(ticker.get("bidPx", 0))
ask = float(ticker.get("askPx", 0))
last = float(ticker.get("last", 0))
check("bidPx > 0", bid > 0, f"bid={bid}")
check("askPx > 0", ask > 0, f"ask={ask}")
check("bid <= ask", bid <= ask, f"bid={bid} ask={ask}")
print(f"     bid={bid}  ask={ask}  last={last}")

# ---------------------------------------------------------------- get_mark_price
banner("get_mark_price — 标记价")
mark = client.get_mark_price(inst_id)
check("mark > 0", mark > 0, f"mark={mark}")
check("mark 在 bid/ask 附近（±5%）", abs(mark - bid) / bid < 0.05,
      f"mark={mark} bid={bid} diff={abs(mark-bid)/bid*100:.2f}%")
print(f"     mark={mark}")

# ---------------------------------------------------------------- get_avail_bal
banner("get_avail_bal — 可用余额")
bal = client.get_avail_bal("USDT")
check("余额 > 0", bal > 0, f"bal={bal}")
print(f"     USDT 可用余额 = {bal:.2f}")

# ---------------------------------------------------------------- get_pos_mode
banner("get_pos_mode — 持仓模式")
mode = client.get_pos_mode()
check("mode 非空", mode in ("net_mode", "long_short_mode"), f"mode={mode}")
print(f"     当前持仓模式 = {mode}")

# ---------------------------------------------------------------- get_position
banner("get_position — 当前持仓")
pos = client.get_position(inst_id)
if pos:
    print(f"     已有持仓: pos={pos.get('pos')} liqPx={pos.get('liqPx')} margin={pos.get('margin')}")
    check("持仓量非零", float(pos.get("pos", 0)) != 0)
else:
    print(f"     无 {inst_id} 持仓")
    check("无持仓返回 None（符合预期）", pos is None)

# ---------------------------------------------------------------- amount_to_contracts
banner("amount_to_contracts — USDT→张数 换算")
amount = float(cfg["contract"]["amount_usdt"])
px = bid  # 做空用 bid
n = client.amount_to_contracts(amount, px, ct_val, lot_sz)
check("张数 >= min_sz", n + 1e-9 >= min_sz, f"n={n} min_sz={min_sz}")
check("张数 ≈ amount/(px*ct_val)", abs(n * px * ct_val - amount) < amount * 0.2,
      f"实际={n * px * ct_val:.2f} USDT 目标={amount}")
print(f"     {amount} USDT @ {px} → {n} 张 ≈ {n * px * ct_val:.2f} USDT")

# ---------------------------------------------------------------- _fmt_sz
banner("_fmt_sz — 数量格式化")
sz_str = client._fmt_sz(n)
check("格式化非空", len(sz_str) > 0)
check("可转回 float", float(sz_str) > 0, f"sz_str={sz_str}")
print(f"     {n} → '{sz_str}'")

# ---------------------------------------------------------------- setup_account
banner("setup_account — 设置持仓模式 + 杠杆")
old_mode = client.get_pos_mode()
client.setup_account(cfg)
new_mode = client.get_pos_mode()
check("持仓模式 = net_mode", new_mode == "net_mode", f"mode={new_mode}")
check("client.pos_mode 已更新", client.pos_mode == "net_mode", f"pos_mode={client.pos_mode}")
print(f"     {old_mode} → {new_mode}")

# ---------------------------------------------------------------- 记录下单前的持仓状态
has_position_before = client.get_position(inst_id) is not None

# ---------------------------------------------------------------- execute_dca
banner("execute_dca — 对手价限价下单（模拟盘真单）")
print("     准备下单…")
ord_id = client.execute_dca(cfg)
if ord_id:
    check("下单返回 ordId", len(ord_id) > 0, f"ordId={ord_id}")
    print(f"     ordId={ord_id}")
    # 等一下让订单状态更新
    time.sleep(2)

    # --- 验证订单 ---
    banner("验证订单状态")
    order_info = client.trade.get_order(instId=inst_id, ordId=ord_id)
    state = order_info["data"][0]["state"]
    check("订单存在", len(order_info["data"]) > 0)
    check("订单成交或部分成交", state in ("filled", "partially_filled"), f"state={state}")
    print(f"     订单状态 = {state}")
else:
    check("下单成功", False, "ord_id 为 None，可能余额不足/最小下单量不够/网络问题")

# ---------------------------------------------------------------- get_position（下单后）
banner("get_position — 下单后确认持仓")
time.sleep(1)
pos2 = client.get_position(inst_id)
if pos2:
    pos_qty = float(pos2.get("pos", 0))
    liq_px = float(pos2.get("liqPx", 0))
    margin = float(pos2.get("margin", 0))
    check("下单后有持仓", pos_qty != 0, f"pos={pos_qty}")
    check("有强平价", liq_px > 0, f"liqPx={liq_px}")
    check("有保证金", margin > 0, f"margin={margin}")
    print(f"     pos={pos_qty} 张  liqPx={liq_px}  margin={margin:.2f} USDT")
else:
    # 之前没有持仓且这次也没新开（可能之前已有反向仓位被平掉了）
    check("下单后有持仓", pos2 is not None, "无持仓，可能被平或网络问题")

# ---------------------------------------------------------------- gap_pct
banner("gap_pct — 安全边际计算")
gap = client.gap_pct(cfg)
if pos2:
    mark2 = client.get_mark_price(inst_id)
    liq2 = float(pos2.get("liqPx", 0))
    check("gap > 0", gap is not None and gap > 0, f"gap={gap}")
    expected = abs(mark2 - liq2) / mark2 * 100
    check("gap ≈ |mark-liq|/mark*100", abs(gap - expected) < 1.0,
          f"gap={gap:.4f} expected={expected:.4f}")
    print(f"     gap = {gap:.2f}%  (mark={mark2}  liq={liq2})")
else:
    check("无持仓 gap=None", gap is None)

# ---------------------------------------------------------------- ensure_liq_level
banner("ensure_liq_level — 补仓检测（幂等验证）")
set_liq = cfg["pause"]["set_liq_px"]
if set_liq and pos2:
    liq_before = float(pos2.get("liqPx", 0))
    print(f"     设定强平线={set_liq}  当前强平价={liq_before}")
    result = client.ensure_liq_level(cfg)
    check("补仓检测不崩溃", result in (True, False))
    pos_after = client.get_position(inst_id)
    liq_after = float(pos_after.get("liqPx", 0)) if pos_after else 0
    print(f"     ensure_liq_level 返回={result}  liq {liq_before} → {liq_after}")
else:
    check("无持仓或未设强平线，跳过", True)

# ---------------------------------------------------------------- _pos_side_for
banner("_pos_side_for — posSide 适配")
check("net_mode + sell → net", client._pos_side_for("sell") == "net")
check("net_mode + buy → net", client._pos_side_for("buy") == "net")

# simulate long_short_mode
client.pos_mode = "long_short_mode"
check("long_short_mode + sell → short", client._pos_side_for("sell") == "short")
check("long_short_mode + buy → long", client._pos_side_for("buy") == "long")
client.pos_mode = "net_mode"  # restore

# ---------------------------------------------------------------- 结果
banner("测试结果")
total = passed + failed
print(f"  通过: {passed}/{total}")
if failed > 0:
    print(f"  ❌ 失败: {failed}")
else:
    print(f"  ✅ 全部通过！")

print("\n注意：模拟盘已下了一单 {inst_id}，请检查 OKX 账户确认。")
