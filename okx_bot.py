# -*- coding: utf-8 -*-
"""
okx_bot.py —— OKX 交易与策略执行模块

对应思路文档的脚本框架：
  - OKXClient        : OKX API 封装（行情 / 下单 / 仓位 / 强平价 / 加保证金 / 行情提醒）
  - setup_account    : 登录后初始化持仓模式与杠杆
  - execute_dca      : 合约执行函数（对手价限价开空一次）
  - ensure_liq_level : 第10点：自动加保证金，使实际强平价达到设定强平线
  - gap_pct          : 第11点：强平价与标记价的差距（百分比）
  - pause_monitor    : 第11点：暂停监控，直到差距恢复安全边际
  - run_loop         : 主执行函数（时间调度 + 暂停判断 + 合约执行 + 目标价停止）

说明：OKX API 没有向 App 发送任意文字消息的接口。价格类提醒（目标价、
安全边际）走 OKX「行情提醒」接口推到 App；下单成交 / 加保证金 / 强平风险
由 OKX App 自身的通知推送覆盖（需在 App 通知设置里打开）。
"""
import logging
import math
import time

from datetime import datetime, date, timedelta, timezone

from okx.Account import AccountAPI
from okx.Trade import TradeAPI
from okx.MarketData import MarketAPI
from okx.PublicData import PublicAPI

from notifier import Notifier
from stats import tracker

logger = logging.getLogger("dtzk")

ERROR_NOTIFY_COOLDOWN = 3600  # 运行异常推送冷却秒数（60分钟），避免网络抖动时反复轰炸手机


def _get_tz(tz_name):
    """返回时区对象；找不到时区数据则兜底用固定 UTC+8（阿里云/腾讯云默认）。"""
    try:
        from zoneinfo import ZoneInfo
        return ZoneInfo(tz_name)
    except Exception:
        return timezone(timedelta(hours=8))


class OKXClient:
    def __init__(self, api_key, secret_key, passphrase, flag,
                 timezone="Asia/Shanghai", proxy=None, notify_cfg=None):
        self.api_key = api_key
        self.secret_key = secret_key
        self.passphrase = passphrase
        self.flag = flag                      # "1"=模拟盘 "0"=实盘
        self.pos_mode = "net_mode"            # 登录初始化时更新
        self.tz = _get_tz(timezone)
        self.proxy = proxy or ""              # 显式代理地址；空=沿用系统/环境代理
        self.notifier = Notifier(notify_cfg or {})

        # 国内网络访问 OKX 必须走代理（OKX 不服务大陆 IP）。
        # proxy 为空时 SDK 的 httpx 会沿用 HTTP_PROXY/HTTPS_PROXY 环境变量。
        self._build_clients()

    def _build_clients(self):
        """创建四个 OKX API 客户端（httpx 长连接）。"""
        self.account = AccountAPI(self.api_key, self.secret_key, self.passphrase,
                                  flag=self.flag, proxy=self.proxy or None)
        self.trade = TradeAPI(self.api_key, self.secret_key, self.passphrase,
                              flag=self.flag, proxy=self.proxy or None)
        self.market = MarketAPI(flag=self.flag, proxy=self.proxy or None)
        self.public = PublicAPI(flag=self.flag, proxy=self.proxy or None)

    def rebuild(self):
        """丢弃并重建全部 API 客户端，清掉可能已损坏的 HTTP/2 长连接。

        代理（mihomo）断连时，httpx 连接池里会残留坏连接；之后即使网络恢复，
        请求仍会失败（表现为无信息的空异常），只有重建客户端才能恢复。
        """
        for c in (self.account, self.trade, self.market, self.public):
            try:
                c.close()
            except Exception:
                pass
        self._build_clients()

    # ---------------------------------------------------------------- 网络容错

    def _retry(self, fn, *args, retries=3, delay=1.0, **kwargs):
        """接口调用失败自动重试（长期运行稳定性）。"""
        for attempt in range(1, retries + 1):
            try:
                return fn(*args, **kwargs)
            except Exception as e:
                if attempt >= retries:
                    raise
                logger.warning("接口调用异常(%s)，%.1f 秒后第%d次重试…",
                               self._safe_msg(e), delay * attempt, attempt + 1)
                # 网络/代理断连会让 httpx 连接池残留坏连接，重建客户端确保下次用全新连接
                self.rebuild()
                time.sleep(delay * attempt)

    # ---------------------------------------------------------------- 基础封装

    @staticmethod
    def _safe_msg(e):
        """把异常/返回值转成 ASCII 安全的字符串，Debian 等非 UTF-8 环境不会崩。

        某些底层网络异常（如 httpcore 连接池耗尽）的 str() 为空，日志和推送
        会只剩空括号 ()，无法定位；这里兜底显示异常类型名。
        """
        try:
            s = str(e)
        except UnicodeEncodeError:
            s = str(e).encode("ascii", errors="replace").decode("ascii")
        if not s and isinstance(e, Exception):
            s = type(e).__name__
        return s

    def test_connection(self):
        """登录校验：能读到账户余额即成功。返回 (ok, 响应)。"""
        try:
            res = self.account.get_account_balance()
            ok = res.get("code") == "0"
            if not ok:
                logger.warning("连接测试失败: code=%s msg=%s",
                               res.get("code"), self._safe_msg(res.get("msg", "")))
            return ok, res
        except Exception as e:
            logger.warning("连接测试异常: %s", self._safe_msg(e))
            return False, {"msg": self._safe_msg(e)}

    def get_ticker(self, inst_id):
        def _do():
            res = self.market.get_ticker(inst_id)
            if res.get("code") != "0":
                raise RuntimeError(f"get_ticker失败 code={res.get('code')} resp={str(res)[:120]}")
            return res["data"][0]
        return self._retry(_do)

    def get_instrument(self, inst_id):
        def _do():
            res = self.public.get_instruments("SWAP", instId=inst_id)
            if res.get("code") != "0":
                raise RuntimeError(f"get_instruments失败 code={res.get('code')} resp={str(res)[:120]}")
            return res["data"][0]
        return self._retry(_do)

    def get_mark_price(self, inst_id):
        """获取标记价格，优先用专用接口，失败则从 ticker 兜底。"""
        def _from_api():
            res = self.public.get_mark_price(instType="SWAP", instId=inst_id)
            if res.get("code") != "0":
                raise RuntimeError(f"get_mark_price code={res.get('code')}")
            px = float(res["data"][0].get("markPx") or 0)
            if px <= 0:
                raise RuntimeError(f"get_mark_price 返回0或空 data={str(res['data'][0])[:120]}")
            return px

        try:
            return self._retry(_from_api, retries=2, delay=0.5)
        except Exception as e:
            logger.warning("专用标记价接口不可用(%s)，降级用ticker兜底", e)

        # 兜底：从 ticker 取 markPx / last
        t = self.get_ticker(inst_id)
        mark = float(t.get("markPx") or t.get("last") or 0)
        if mark <= 0:
            logger.warning("ticker 也未取到有效标记价，返回0 data=%s", str(t)[:200])
        return mark

    def get_pos_mode(self):
        """读取当前持仓模式：net_mode / long_short_mode。"""
        try:
            res = self.account.get_account_config()
            return res["data"][0]["posMode"]
        except Exception:
            return "net_mode"

    def get_position(self, inst_id):
        """返回该合约的非零持仓 dict；无持仓返回 None。"""
        def _do():
            res = self.account.get_positions(instId=inst_id)
            for p in res.get("data", []):
                try:
                    if float(p.get("pos") or 0) != 0:
                        return p
                except (TypeError, ValueError):
                    continue
            return None
        return self._retry(_do)

    def get_avail_bal(self, ccy="USDT"):
        """返回某币种可用余额（失败返回 0.0）。"""
        def _do():
            res = self.account.get_account_balance(ccy=ccy)
            for d in res.get("data", []):
                for det in d.get("details", []):
                    if det.get("ccy") == ccy:
                        return float(det.get("availBal") or 0)
            return 0.0
        try:
            return self._retry(_do)
        except Exception as e:
            logger.warning("读取余额失败: %s", e)
            return 0.0

    def _pos_side_for(self, side):
        if self.pos_mode == "long_short_mode":
            return "short" if side == "sell" else "long"
        return "net"

    # ---------------------------------------------------------------- 初始化

    def setup_account(self, cfg):
        """设置持仓模式（优先单向）+ 杠杆。"""
        inst_id = cfg["contract"]["inst_id"]
        mode = self.get_pos_mode()
        if mode != "net_mode":
            res = self.account.set_position_mode("net_mode")
            if res.get("code") == "0":
                mode = "net_mode"
                logger.info("已切换为单向持仓模式")
            else:
                logger.warning("切换单向持仓失败(%s)，按当前模式适配 posSide", res.get("msg"))
                mode = self.get_pos_mode()
        self.pos_mode = mode

        lever = cfg["contract"]["leverage"]
        mgn = cfg["contract"]["mgn_mode"]
        ps = "net" if mode == "net_mode" else "short"
        res = self.account.set_leverage(lever, mgn, instId=inst_id, posSide=ps)
        if res.get("code") != "0":
            logger.warning("设置杠杆失败: %s（可忽略，继续执行）", res.get("msg"))

    # ---------------------------------------------------------------- 合约执行（文档 1~7）

    def amount_to_contracts(self, amount_usdt, px, ct_val, lot_sz):
        """USDT 金额 -> 合约张数（向下取整到 lot_sz 的整数倍）。

        注：OKX SWAP 现支持小数张（如 BTC-USDT-SWAP 的 lotSz=0.01 张），
        因此返回 float，不取整。
        """
        if px <= 0 or ct_val <= 0 or lot_sz <= 0:
            return 0.0
        raw = amount_usdt / (px * ct_val)
        n = math.floor(raw / lot_sz) * lot_sz
        return round(n, 10)

    @staticmethod
    def _fmt_sz(v):
        """把张数格式化成 OKX 接受的数量字符串（去尾零）。"""
        s = f"{v:.10f}".rstrip("0").rstrip(".")
        return s or "0"

    def execute_dca(self, cfg):
        """限价开单一次。同向价(post_only)被拒自动重试，每次重试刷新盘口价。"""
        inst_id = cfg["contract"]["inst_id"]
        side = cfg["contract"]["side"]
        amount = float(cfg["contract"]["amount_usdt"])
        price_mode = cfg["contract"].get("price_mode", "opposite_1")

        # 合约信息一次就够了（tickSz/面值不变）
        inst = self.get_instrument(inst_id)
        ct_val = float(inst["ctVal"])
        lot_sz = float(inst["lotSz"])
        min_sz = float(inst.get("minSz") or lot_sz)
        tick_sz = float(inst.get("tickSz") or 0.1)

        do_retry = price_mode.startswith("same")
        retry_max = int(cfg["runtime"].get("retry_max", 5)) if do_retry else 1
        retry_interval = float(cfg["runtime"].get("retry_interval_sec", 1))
        fill_wait = int(cfg["runtime"]["fill_wait_sec"])

        for attempt in range(retry_max):
            # 每次重试刷新盘口价
            ticker = self.get_ticker(inst_id)
            bid = float(ticker["bidPx"])
            ask = float(ticker["askPx"])

            # 根据价格模式计算委托价（1/5 指深度档位：卖一/卖五/买一/买五）
            if side == "sell":
                px = {
                    "same_1": ask, "same_5": ask + 4 * tick_sz,
                    "opposite_1": bid, "opposite_5": bid - 4 * tick_sz,
                }.get(price_mode, ask)
            else:
                px = {
                    "same_1": bid, "same_5": bid - 4 * tick_sz,
                    "opposite_1": ask, "opposite_5": ask + 4 * tick_sz,
                }.get(price_mode, bid)

            contracts = self.amount_to_contracts(amount, px, ct_val, lot_sz)
            if contracts + 1e-9 < min_sz:
                self.notify("下单跳过",
                            f"定投金额 {amount} USDT 按报价 {px} 换算不足最小下单量"
                            f"（该合约至少 {min_sz} 张 ≈ {min_sz * px * ct_val:.2f} USDT），"
                            f"本次定投已跳过，请手动在 OKX 里执行本次定投")
                tracker.count_skipped()
                return None

            avail = self.get_avail_bal()
            lever = float(cfg["contract"]["leverage"])
            est_margin = amount / lever if lever > 0 else amount
            logger.info("下单前可用余额: %.2f USDT，预估保证金: %.2f USDT", avail, est_margin)

            pos_side = self._pos_side_for(side)
            sz = self._fmt_sz(contracts)
            ord_type = "post_only" if price_mode.startswith("same") else "limit"

            res = self.trade.place_order(
                instId=inst_id,
                tdMode=cfg["contract"]["mgn_mode"],
                side=side,
                ordType=ord_type,
                sz=sz,
                px=f"{px:.6f}",
                posSide=pos_side,
            )
            if res.get("code") != "0":
                err = res.get("msg") or f"code={res.get('code')}"
                self.notify("下单失败",
                            f"{err}，可用余额为 {avail:.2f} USDT。"
                            f"本次挂单失败故跳过本次定投，请手动在 OKX 上挂单进行本次定投")
                tracker.count_failed()
                return None

            ord_id = res["data"][0]["ordId"]
            logger.info("已提交限价单 ordId=%s 张数=%s 价格=%.6f side=%s posSide=%s",
                        ord_id, sz, px, side, pos_side)

            result = self._wait_fill(inst_id, ord_id, cfg)

            if result == "filled":
                self.notify("策略执行成功，本次定投订单已成交", "确认脚本存活")
                tracker.count_success()
                return ord_id

            if result == "timeout":
                self.notify("订单未成交",
                            f"订单 {ord_id} 在 {fill_wait} 秒内未成交，请留意是否成交或手动处理，"
                            f"本次定投已成功挂单，确认存活")
                tracker.count_unfilled()
                return None

            # result == "canceled"
            if do_retry and attempt + 1 < retry_max:
                logger.info("同向价挂单被取消，%.1fs 后重试（第 %d/%d 次）",
                            retry_interval, attempt + 1, retry_max)
                time.sleep(retry_interval)
                continue

            # 最终失败
            self.notify("订单未成交",
                        f"订单 {ord_id} 已被取消，对手价可能已变化，"
                        f"本次定投已跳过，请检查仓位手动执行本次定投")
            tracker.count_unfilled()
            return None

        return None

    def _wait_fill(self, inst_id, ord_id, cfg):
        """等待订单成交确认（最长 fill_wait_sec 秒）。返回 "filled" / "canceled" / "timeout"。"""
        waited = 0
        limit = int(cfg["runtime"]["fill_wait_sec"])
        while waited < limit:
            try:
                o = self.trade.get_order(instId=inst_id, ordId=ord_id)
                state = o["data"][0]["state"]
                if state in ("filled", "partially_filled"):
                    logger.info("订单 %s 成交 state=%s", ord_id, state)
                    return "filled"
                if state in ("canceled", "canceling"):
                    logger.warning("订单 %s 被取消 state=%s", ord_id, state)
                    return "canceled"
            except Exception as e:
                logger.warning("查询订单 %s 异常: %s", ord_id, e)
            time.sleep(1)
            waited += 1
        logger.warning("订单 %s 在 %s 秒内未完全成交", ord_id, limit)
        return "timeout"

    # ---------------------------------------------------------------- 第10点：自动加保证金

    def ensure_liq_level(self, cfg):
        """使实际强平价达到设定的强平线；余额不足则提醒手动添加。

        做空：加保证金推高强平价（liq >= set_liq 达标）。
        做多：加保证金压低强平价（liq <= set_liq 达标）。
        """
        set_liq = cfg["pause"]["set_liq_px"]
        if not set_liq:
            return True
        inst_id = cfg["contract"]["inst_id"]
        side = cfg["contract"]["side"]
        tol = max(0.000001 * set_liq, 0.000001)

        for attempt in range(1, 7):
            pos = self.get_position(inst_id)
            if not pos:
                return True
            liq = float(pos.get("liqPx") or 0)
            if liq <= 0:
                logger.warning("未获取到强平价，跳过自动补保证金")
                return True

            if side == "sell" and liq >= set_liq - tol:
                logger.info("强平价 %.4f 已不低于设定值 %.4f，无需补仓", liq, set_liq)
                return True
            if side == "buy" and liq <= set_liq + tol:
                logger.info("强平价 %.4f 已不高于设定值 %.4f，无需补仓", liq, set_liq)
                return True

            mark = self.get_mark_price(inst_id)
            margin = float(pos.get("margin") or 0)
            gap_cur = abs(mark - liq)
            gap_tgt = abs(mark - set_liq)
            if gap_cur <= 0:
                gap_cur = 1e-9

            need = margin * (gap_tgt / gap_cur - 1.0)
            avail = self.get_avail_bal()
            logger.info("补仓前可用余额: %.2f USDT，预估需补: %.2f USDT", avail, need)
            chunk = min(max(need, 1.0), avail * 0.9)
            if avail < 1.0 or chunk < 1.0:
                self.notify("余额不足",
                            f"可用余额为 {avail:.2f} USDT，不足以补足保证金至强平价 "
                            f"{set_liq}（当前强平价 {liq}），请手动划转可用资金！")
                return False

            pos_side = pos.get("posSide") or self._pos_side_for(side)
            res = self.account.adjustment_margin(inst_id, pos_side, "add", f"{chunk:.2f}")
            if res.get("code") != "0":
                logger.warning("补保证金失败(第%d次): %s", attempt, res.get("msg"))
                if attempt >= 3:
                    self.notify("补仓失败",
                                f"自动补保证金连续失败，请手动在 OKX App 添加保证金！")
                    return False
            else:
                logger.info("第%d次补仓 %.2f USDT（当前强平价 %.4f → 目标 %.4f）",
                            attempt, chunk, liq, set_liq)
            time.sleep(1)

        self.notify("补仓未达标",
                    f"多次补仓后强平价仍未达到设定值 {set_liq}，请手动添加保证金！")
        return False

    # ---------------------------------------------------------------- 第11点：安全边际 & 暂停

    @staticmethod
    def _target_reached(mark, target_px, side):
        """做空=价格跌到目标以下；做多=价格涨到目标以上。"""
        if target_px is None:
            return False
        if side == "sell":
            return mark <= target_px
        else:
            return mark >= target_px

    def gap_pct(self, cfg):
        """强平价与标记价的差距百分比 = |强平价-标记价|/标记价*100。无仓位返回 None。"""
        inst_id = cfg["contract"]["inst_id"]
        pos = self.get_position(inst_id)
        if not pos:
            return None
        liq = float(pos.get("liqPx") or 0)
        if liq <= 0:
            return None
        mark = self.get_mark_price(inst_id)
        if mark <= 0:
            return None
        return abs(mark - liq) / mark * 100.0

    def pause_monitor(self, cfg):
        """差距小于安全边际时暂停定投并监控，直到恢复。返回 'resume' 或 'target_hit'。"""
        safety = float(cfg["pause"]["safety_margin_pct"])
        monitor_sec = int(cfg["runtime"]["monitor_sec"])
        inst_id = cfg["contract"]["inst_id"]
        self.notify("暂停定投",
                    f"强平价与标记价差距小于 {safety}%，暂停定投，开始实时监控…")

        while True:
            target_px = cfg["pause"]["target_px"]
            side = cfg["contract"]["side"]
            if target_px:
                mark = self.get_mark_price(inst_id)
                if self._target_reached(mark, target_px, side):
                    op = "≤" if side == "sell" else "≥"
                    self.notify("目标价到达",
                                f"监控期间标记价 {mark} {op} 目标价 {target_px}，停止定投，脚本退出")
                    return "target_hit"

            # 若设定了强平线，暂停期间也尝试自动补仓来恢复安全边际
            if cfg["pause"]["set_liq_px"]:
                self.ensure_liq_level(cfg)

            gap = self.gap_pct(cfg)
            if gap is not None and gap >= safety:
                self.notify("恢复定投",
                            f"强平价与标记价差距已恢复至 {gap:.2f}%（≥{safety}%），恢复定投")
                return "resume"
            time.sleep(monitor_sec)

    # ---------------------------------------------------------------- 主执行循环（文档 8~12）

    @staticmethod
    def _parse_date(s):
        try:
            return datetime.strptime(s, "%Y-%m-%d").date()
        except (TypeError, ValueError):
            return None

    def _date_valid(self, now, cfg):
        """日期有效性：在起止范围内，且符合日期类型（每天/工作日=周一至周五）。"""
        t = cfg["time"]
        d = now.date()
        start = self._parse_date(t.get("start_date"))
        end = self._parse_date(t.get("end_date"))
        if start and d < start:
            return False
        if end and d > end:
            return False
        if t.get("date_type") == "weekday" and d.weekday() >= 5:
            return False
        return True

    @staticmethod
    def _norm_hm(s):
        """把 '3:43' / '03:43' 统一规范化为 '03:43'，防止字符串匹配错位。"""
        try:
            return datetime.strptime(str(s), "%H:%M").strftime("%H:%M")
        except (ValueError, TypeError):
            return str(s)

    def _current_slot(self, now, cfg):
        """当前时刻若正好落在某个定投时间点所在分钟，返回 'YYYY-MM-DD HH:MM'，否则 None。

        只在精确分钟（HH:MM 完全相等）内触发，绝不提前，也不会重复触发。
        """
        hm = now.strftime("%H:%M")
        for t in cfg["time"]["times"]:
            if hm == self._norm_hm(t):
                return now.strftime("%Y-%m-%d %H:%M")
        return None

    def _missed_slots(self, now, cfg, done, since=None):
        """暂停恢复后：返回当天已过时间但未执行的定投 slot 列表。

        since: 只返回该时间之后的 slot（即暂停期间错过的），None 表示全部。
        """
        missed = []
        today_str = now.strftime("%Y-%m-%d")
        for t in cfg["time"]["times"]:
            hm = self._norm_hm(t)
            slot_key = f"{today_str} {hm}"
            if slot_key in done:
                continue
            try:
                slot_dt = datetime.strptime(slot_key, "%Y-%m-%d %H:%M")
                slot_dt = slot_dt.replace(tzinfo=now.tzinfo)
            except (ValueError, TypeError):
                continue
            if slot_dt < now and (since is None or slot_dt >= since):
                missed.append(slot_key)
        return missed

    def run_loop(self, cfg):
        """主执行函数：时间调度 → 周期性安全边际监控 → 合约执行 → 自动补仓，直到结束/目标价。

        长期运行设计：单次迭代内任何异常都会被捕获、记录后继续，
        不会导致整个脚本退出。

        安全边际检查独立于定投时间点，按 monitor_interval_sec 周期运行。
        gap 缩小时自动触发补仓检测（趋势触发，不做无意义的定时轮询）。
        """
        interval = max(int(cfg["runtime"]["interval_sec"]), 5)
        monitor_interval = max(int(cfg["runtime"].get("monitor_interval_sec", 60)), interval)
        inst_id = cfg["contract"]["inst_id"]
        safety = float(cfg["pause"]["safety_margin_pct"])
        end = self._parse_date(cfg["time"].get("end_date"))
        done = set()     # 已执行过的定投时间点 'YYYY-MM-DD HH:MM'
        prev_gap = None  # 上一轮安全边际差距，用于判断缩小趋势
        last_monitor = datetime.now(self.tz) - timedelta(seconds=monitor_interval)
        in_error = False          # 是否处于连续异常状态（用于恢复提示与推送冷却）
        last_error_notify = 0.0   # 上次推送"运行异常"的时间戳

        # 启动时校验合约有效（避免 instId 拼错白跑）
        try:
            inst = self.get_instrument(inst_id)
            logger.info("合约校验通过: %s 面值=%s 最小下单=%s 张",
                        inst_id, inst.get("ctVal"), inst.get("minSz"))
        except Exception as e:
            logger.error("合约 %s 校验失败（请检查是否正确，如 BTC-USDT-SWAP）: %s", inst_id, e)
            return

        tracker.start_session(inst_id, cfg["contract"]["side"])
        logger.info("开始定投做空执行循环（时区=%s），合约=%s，每日时间点=%s，检测间隔=%ss",
                    self.tz, inst_id, cfg["time"]["times"], monitor_interval)

        try:
            while True:
                try:
                    now = datetime.now(self.tz)

                    # 网络故障后探活：能读到余额说明已恢复，推一次"运行恢复"
                    if in_error:
                        try:
                            ok, _ = self.test_connection()
                        except Exception:
                            ok = False
                        if ok:
                            logger.info("网络/代理已恢复，恢复正常执行")
                            self.notify("运行恢复", "网络或代理已恢复，脚本继续正常运行")
                            in_error = False

                    if end and now.date() > end:
                        self.notify("定投结束",
                                    f"已超过结束日期 {end}，定投结束，脚本退出")
                        return

                    # 第12点：目标价检查（每次循环都查，及时响应）
                    target_px = cfg["pause"]["target_px"]
                    if target_px:
                        mark = self.get_mark_price(inst_id)
                        if self._target_reached(mark, target_px, cfg["contract"]["side"]):
                            op = "≤" if cfg["contract"]["side"] == "sell" else "≥"
                            self.notify("目标价到达",
                                        f"标记价 {mark} {op} 目标价 {target_px}，定投停止，脚本退出")
                            return

                    # 第11点：周期性安全边际检查（独立于定投时间点）
                    if safety > 0 and (now - last_monitor).total_seconds() >= monitor_interval:
                        gap = self.gap_pct(cfg)
                        if gap is not None:
                            if gap < safety:
                                # 差距跌破安全边际 → 暂停定投，持续监控直到恢复
                                pause_start = now
                                res = self.pause_monitor(cfg)
                                prev_gap = None
                                last_monitor = now
                                if res == "target_hit":
                                    return
                                # 检查暂停期间是否错过了定投时间点
                                now2 = datetime.now(self.tz)
                                missed = self._missed_slots(now2, cfg, done, since=pause_start)
                                if missed:
                                    self.notify("定投错过",
                                                f"安全边际暂停期间，以下时段定投未执行: "
                                                + ", ".join(m[-5:] for m in missed)
                                                + "，请手动在 OKX 上执行错过的定投")
                                    for _ in missed:
                                        tracker.count_paused()
                                    for m in missed:
                                        done.add(m)
                                continue
                            # gap 在缩小（逼近强平价）→ 趋势触发补仓
                            if prev_gap is not None and gap < prev_gap:
                                logger.info("安全边际缩小 %.2f%% → %.2f%%，触发补仓检测", prev_gap, gap)
                                self.ensure_liq_level(cfg)
                            prev_gap = gap
                        else:
                            prev_gap = None   # 无仓位，重置趋势
                        last_monitor = now

                    # --- 定投时间点判断 + 执行 ---
                    if not self._date_valid(now, cfg):
                        time.sleep(interval)
                        continue

                    slot = self._current_slot(now, cfg)
                    if slot is None or slot in done:
                        time.sleep(interval)
                        continue

                    # 下单前强制检查安全边际（弥补周期性检查的窗口期）
                    if safety > 0:
                        gap = self.gap_pct(cfg)
                        if gap is not None:
                            if gap < safety:
                                # 用 slot 自身时间作为暂停起点，确保本 slot 被计入错过
                                try:
                                    pause_start = datetime.strptime(slot, "%Y-%m-%d %H:%M").replace(tzinfo=now.tzinfo)
                                except (ValueError, TypeError):
                                    pause_start = now
                                res = self.pause_monitor(cfg)
                                prev_gap = None
                                last_monitor = now
                                if res == "target_hit":
                                    return
                                # 检查暂停期间是否错过了定投时间点
                                now2 = datetime.now(self.tz)
                                missed = self._missed_slots(now2, cfg, done, since=pause_start)
                                if missed:
                                    self.notify("定投错过",
                                                f"安全边际暂停期间，以下时段定投未执行: "
                                                + ", ".join(m[-5:] for m in missed)
                                                + "，请手动在 OKX 上执行错过的定投")
                                    for _ in missed:
                                        tracker.count_paused()
                                    for m in missed:
                                        done.add(m)
                                continue
                            prev_gap = gap  # 顺手更新趋势，保持追踪连续性

                    # 第10点：定投执行 + 补仓
                    self.execute_dca(cfg)
                    self.ensure_liq_level(cfg)
                    done.add(slot)
                    time.sleep(interval)
                except KeyboardInterrupt:
                    self.notify("手动停止",
                               "已收到 Ctrl+C，定投已暂停（当前仓位不受影响）。配置已保留，重启脚本即可继续。")
                    return
                except Exception as e:
                    msg = self._safe_msg(e)
                    logger.warning("执行循环出现异常，%s 秒后继续: %s", interval, msg)
                    now_ts = time.time()
                    if not in_error or now_ts - last_error_notify >= ERROR_NOTIFY_COOLDOWN:
                        self.notify("运行异常", f"脚本出现异常({msg})，{interval}秒后自动恢复，请检查网络或代理")
                        last_error_notify = now_ts
                    in_error = True
                    try:
                        time.sleep(interval)
                    except KeyboardInterrupt:
                        self.notify("手动停止",
                               "已收到 Ctrl+C，定投已暂停（当前仓位不受影响）。配置已保留，重启脚本即可继续。")
                        return
        finally:
            tracker.end_session()

    # ---------------------------------------------------------------- 提醒

    def notify(self, title, msg):
        """提醒：打印到控制台 + 推到手机（若已配置推送渠道）。"""
        logger.info("【%s】%s", title, msg)
        self.notifier.send(f"OKX {title}", f"{msg}")
