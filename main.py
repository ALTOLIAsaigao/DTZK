# -*- coding: utf-8 -*-
"""
main.py —— OKX 定投做空脚本 · 命令行界面

运行: python main.py

菜单结构（对应思路文档）：
  登录 -> 主菜单(执行策略/合约配置/时间配置/暂停配置/重新登陆)
"""
import logging
import os
import sys
from datetime import datetime
from logging.handlers import RotatingFileHandler

from config import BASE_DIR, load_config, save_config
from okx_bot import OKXClient
from menu import select as menu_select

logger = logging.getLogger("dtzk")


def setup_logging():
    """控制台 + 文件（dtzk.log，1MB 轮转）双输出，方便服务器长期运行后查看日志。"""
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", "%Y-%m-%d %H:%M:%S")
    root = logging.getLogger("dtzk")
    root.setLevel(logging.INFO)

    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(fmt)
    root.addHandler(console)

    log_path = os.path.join(BASE_DIR, "dtzk.log")
    try:
        fh = RotatingFileHandler(log_path, maxBytes=1_000_000, backupCount=5, encoding="utf-8")
        fh.setFormatter(fmt)
        root.addHandler(fh)
    except OSError as e:
        print(f"  警告：无法创建日志文件 {log_path}：{e}")


# ---------------------------------------------------------------- 通用输入工具

def _normalize_ascii(s):
    """把中文输入法打出的全角符号转成英文半角，避免配置/密码匹配出错。"""
    import unicodedata
    s = unicodedata.normalize("NFKC", s)
    # NFKC 能处理大部分全角字符，剩下这些手动补
    table = str.maketrans({
        "：": ":", "，": ",", "？": "?", "！": "!",
        "（": "(", "）": ")", "；": ";", "＂": "\"",
        "【": "[", "】": "]", "～": "~",
    })
    return s.translate(table)


def input_str(prompt, default=None, allow_empty=False):
    """读一行字符串；允许空回车时返回 default。无交互输入(EOF)返回 default。"""
    if default is not None:
        hint = f"[当前值: {default}] "
    else:
        hint = ""
    while True:
        try:
            val = input(f"{hint}{prompt}: ").strip()
        except EOFError:
            print("  (无交互输入，使用默认值)")
            return default
        if val == "" and default is not None:
            return default
        if val == "" and allow_empty:
            return None
        if val != "":
            return _normalize_ascii(val)
        print("  输入不能为空，请重新输入。")


def input_float(prompt, default=None, min_v=None, allow_empty=False, clear_char=None):
    """读一个浮点数；空回车返回 default（或 None），输入 clear_char 返回 None 表示关闭。"""
    while True:
        val = input_str(prompt, default=None if default is None else default, allow_empty=allow_empty)
        if val is None:
            return None
        if clear_char and str(val).lower() == clear_char:
            return None
        try:
            f = float(val)
            if min_v is not None and f < min_v:
                print(f"  数值不能小于 {min_v}，请重新输入。")
                continue
            return f
        except ValueError:
            extra = f"，或输入 {clear_char} 关闭" if clear_char else ""
            print(f"  请输入有效数字{extra}。")


def input_time(prompt, default=None):
    """读 HH:MM 时间；校验格式。"""
    while True:
        val = input_str(prompt, default=default)
        try:
            datetime.strptime(val, "%H:%M")
            return val
        except ValueError:
            print("  时间格式应为 HH:MM（如 10:00）。")


# ---------------------------------------------------------------- 登录

def build_client(cfg):
    """用 config.json 里已保存的凭证构建 OKXClient（不联网测试）。"""
    api = cfg["api"]
    return OKXClient(
        api_key=api["api_key"],
        secret_key=api["secret_key"],
        passphrase=api["passphrase"],
        flag=api["flag"],
        timezone=cfg["runtime"].get("timezone", "Asia/Shanghai"),
        proxy=cfg["runtime"].get("proxy") or None,
        notify_cfg=cfg.get("notify", {}),
    )


def login(cfg):
    """登录函数：输入 API 凭证 -> 测试连接 -> 保存到 config.json。返回 OKXClient 或 None。"""
    print("\n" + "=" * 56)
    print("OKX 定投做空脚本 —— 登录")
    print("=" * 56)
    print("若登录失败，检查下 API 的 IP 白名单是不是开着，开着的话关掉。")
    print("国内走代理/VPN 出口 IP 会变，开了白名单连不上。")
    print("-" * 56)
    api = cfg["api"]
    flag = menu_select(
        "选择运行环境：",
        [("模拟盘（推荐先测试）", "1"), ("实盘", "0")],
        default=api.get("flag", "1"),
    )
    api_key = input_str("请输入 API Key", default=api.get("api_key") or None)
    secret_key = input_str("请输入 Secret Key", default=api.get("secret_key") or None)
    passphrase = input_str("请输入 Passphrase（你自己设定的密码）", default=api.get("passphrase") or None)

    api.update({"api_key": api_key, "secret_key": secret_key,
                "passphrase": passphrase, "flag": flag})
    client = build_client(cfg)
    print("\n正在测试连接（读取账户余额）…")
    ok, res = client.test_connection()
    if not ok:
        print(f"\n❌ 连接失败: {res.get('msg') or res.get('code')}")
        print("   请检查：APIKey 权限（需要 读取+交易）、时间是否同步、是否开启 IP 白名单。")
        return None
    print("\n✅ 登录成功！")
    api["api_key"], api["secret_key"], api["passphrase"], api["flag"] = api_key, secret_key, passphrase, flag
    save_config(cfg)
    return client


# ---------------------------------------------------------------- 合约配置（文档 1~7）

def contract_config(cfg):
    print("\n" + "-" * 56)
    print("合约配置界面")
    print("-" * 56)
    c = cfg["contract"]

    inst_id = input_str("请输入合约（如 BTC-USDT-SWAP）", default=c["inst_id"])
    mgn_mode = menu_select(
        "请选择逐仓或是全仓:",
        [("逐仓", "isolated"), ("全仓", "cross")],
        default=c["mgn_mode"],
    )
    leverage = input_str("请输入杠杆（默认为1x）", default=c.get("leverage", "1"))
    # 4. 委托价格模式（同向价=post_only挂单，对手价=limit吃单）
    price_labels = {
        "same_1": "同向价1（卖一，post_only挂单，推荐）",
        "same_5": "同向价5（卖五，post_only挂单）",
        "opposite_1": "对手价1（买一，limit吃单）",
        "opposite_5": "对手价5（买五，limit吃单）",
    }
    price_mode = menu_select(
        "请选择委托价格（post_only 只挂单不吃单，推荐同向价1，挂单手续费最低）：",
        [(v, k) for k, v in price_labels.items()],
        default=c.get("price_mode", "same_1"),
    )
    amount = input_str("请输入下单的数量（默认单位为USDT）", default=c["amount_usdt"])
    side = menu_select(
        "请选择买入或者卖出:",
        [("卖出（开空，定投做空选这个）", "sell"), ("买入", "buy")],
        default=c["side"],
    )

    c.update({
        "inst_id": inst_id.strip().upper(),
        "mgn_mode": mgn_mode,
        "leverage": leverage,
        "price_mode": price_mode,
        "amount_usdt": amount,
        "side": side,
    })
    save_config(cfg)
    print("\n✅ 合约配置已保存。")
    print(f"   合约={c['inst_id']}  保证金={mgn_mode}  杠杆={leverage}x  "
          f"价格={price_labels[price_mode]}  数量={amount}USDT  方向={side}")


# ---------------------------------------------------------------- 时间配置（文档 8~9）

def date_config(cfg):
    print("\n" + "-" * 56)
    print("日期配置界面")
    print("-" * 56)
    t = cfg["time"]
    start = input_str("请输入开始时间（YYYY-MM-DD）", default=t.get("start_date") or None)
    end = input_str("请输入结束时间（YYYY-MM-DD）", default=t.get("end_date") or None)
    date_type = menu_select(
        "请选择日期类型:",
        [("期间每天", "everyday"), ("工作日（周一至周五）", "weekday")],
        default=t.get("date_type", "everyday"),
    )
    t["start_date"], t["end_date"], t["date_type"] = start, end, date_type
    save_config(cfg)
    print(f"\n✅ 日期配置已保存：{start} ~ {end}，类型={date_type}")


def freq_config(cfg):
    print("\n" + "-" * 56)
    print("频率与具体定投时间配置界面")
    print("-" * 56)
    t = cfg["time"]
    freq = input("  请输入一天内定投的频率（默认为1）: ").strip() or "1"
    try:
        freq = int(freq)
    except ValueError:
        freq = 1
    freq = max(1, min(freq, 10))

    times = []
    for i in range(1, freq + 1):
        if i == 1 and t["times"]:
            default = t["times"][0]
        else:
            default = None
        hhmm = input_time(f"请输入定投的具体时间{i}（HH:MM）", default=default)
        if hhmm:
            # 统一规范化为 "HH:MM"（如 3:43 -> 03:43），避免匹配错位
            try:
                hhmm = datetime.strptime(hhmm, "%H:%M").strftime("%H:%M")
            except ValueError:
                pass
        if hhmm and hhmm not in times:
            times.append(hhmm)
    times.sort()
    t["times"] = times
    save_config(cfg)
    print(f"✅ 定投时间已保存：每天 {times}（共 {len(times)} 次）")


def time_config(cfg):
    while True:
        choice = menu_select("时间配置界面", [
            ("日期配置", "date"),
            ("频率与具体定投时间配置", "freq"),
            ("返回主菜单", "back"),
        ], default="date")
        if choice == "date":
            date_config(cfg)
        elif choice == "freq":
            freq_config(cfg)
        else:
            return


# ---------------------------------------------------------------- 暂停配置（文档 10~12）

def pause_config(cfg):
    while True:
        p = cfg["pause"]
        choice = menu_select("暂停配置界面", [
            ("设定仓位强平线", "liq"),
            ("设定目标价格", "target"),
            ("设定安全边际（标记价格与强平价差距）", "safety"),
            ("返回主菜单", "back"),
        ], default="liq")
        if choice == "liq":
            print("\n注意：脚本会在定投时自动检查仓位强平线并自动加入保证金，")
            print("      使实际仓位强平线等于设定强平线。回车保持当前值，输入 n 关闭（不启用）。")
            val = input_float("请输入设定强平线", default=p.get("set_liq_px"), clear_char='n')
            p["set_liq_px"] = val
            save_config(cfg)
            print(f"  ✅ 设定强平线 = {val}")
        elif choice == "target":
            print("\n注意：做空时标记价 ≤ 目标价停止，做多时标记价 ≥ 目标价停止。")
            print("      回车保持当前值，输入 n 关闭。")
            val = input_float("请输入目标价格", default=p.get("target_px"), clear_char='n')
            p["target_px"] = val
            save_config(cfg)
            print(f"  ✅ 目标价格 = {val}")
        elif choice == "safety":
            print("\n注意：当仓位实际强平线距离与标记价格差距小于 X% 时，")
            print("      将暂停定投并发告警，直到差距恢复才继续。")
            val = input_float("请输入安全边际差距X（百分比）", default=p.get("safety_margin_pct", 0.0), min_v=0.0)
            p["safety_margin_pct"] = val
            save_config(cfg)
            print(f"  ✅ 安全边际 = {val}%")
        else:
            return


# ---------------------------------------------------------------- 推送配置

def \
        push_config(cfg):
    """推送配置界面：选择渠道 -> 填凭证 -> 可发测试消息。"""
    from notifier import Notifier
    n = cfg["notify"]
    channel_names = {
        "none": "未开启", "serverchan": "Server酱(微信)", "pushplus": "PushPlus(微信)",
        "bark": "Bark(iOS)", "telegram": "Telegram",
    }
    while True:
        current = channel_names.get(n.get("channel", "none"), n.get("channel"))
        choice = menu_select(f"推送配置界面（当前: {current}）", [
            ("Server酱（免费推微信）", "serverchan"),
            ("PushPlus（免费推微信）", "pushplus"),
            ("Bark（iPhone）", "bark"),
            ("Telegram", "telegram"),
            ("关闭推送", "off"),
            ("发送测试消息", "test"),
            ("返回主菜单", "back"),
        ], default="back")

        if choice == "serverchan":
            print("\nServer酱：去 https://sct.ftqq.com 用微信扫码登录，拿 SendKey（sctxxx.xxxx 格式）")
            key = input_str("请输入 Server酱 SendKey", default=n.get("serverchan_key") or None)
            n.update({"channel": "serverchan", "serverchan_key": key, "enabled": True})
            save_config(cfg)
            print("  ✅ 已选择 Server酱。")
        elif choice == "pushplus":
            print("\nPushPlus：去 https://www.pushplus.plus 注册，个人中心复制 token")
            token = input_str("请输入 PushPlus token", default=n.get("pushplus_token") or None)
            n.update({"channel": "pushplus", "pushplus_token": token, "enabled": True})
            save_config(cfg)
            print("  ✅ 已选择 PushPlus。")
        elif choice == "bark":
            print("\nBark：iPhone 安装 Bark App，拿到推送地址（如 https://api.day.app/你的设备key）")
            url = input_str("请输入 Bark 推送地址", default=n.get("bark_url") or None)
            n.update({"channel": "bark", "bark_url": url, "enabled": True})
            save_config(cfg)
            print("  ✅ 已选择 Bark。")
        elif choice == "telegram":
            print("\nTelegram：找 @BotFather 创建 Bot 拿 token；再向 @userinfobot 发送任意消息拿 chat_id")
            token = input_str("请输入 Telegram Bot Token", default=n.get("telegram_bot_token") or None)
            chat = input_str("请输入 Telegram Chat ID", default=n.get("telegram_chat_id") or None)
            n.update({"channel": "telegram", "telegram_bot_token": token,
                      "telegram_chat_id": chat, "enabled": True})
            save_config(cfg)
            print("  ✅ 已选择 Telegram。")
        elif choice == "off":
            n.update({"channel": "none", "enabled": False})
            save_config(cfg)
            print("  ✅ 已关闭推送。")
        elif choice == "test":
            ok, msg = Notifier(n).test()
            print(f"  {'✅' if ok else '❌'} {msg}")
        else:
            return


# ---------------------------------------------------------------- 执行策略

def run_strategy(cfg, client, confirm=True):
    if client is None:
        print("\n请先登录。")
        client = login(cfg)
        if client is None:
            return None
    c, t, p = cfg["contract"], cfg["time"], cfg["pause"]
    if not t.get("start_date") or not t.get("end_date"):
        print("\n❌ 请先在【时间配置】里设置开始/结束日期。")
        return client
    if not t.get("times"):
        print("\n❌ 请先在【时间配置】里设置定投时间点。")
        return client

    # 校验强平线与目标价的关系
    set_liq = p.get("set_liq_px")
    target = p.get("target_px")
    side = c["side"]
    if set_liq and target:
        if side == "sell" and set_liq <= target:
            print(f"\n❌ 做空时设定强平线({set_liq})必须大于目标价格({target})，请重新配置。")
            return client
        if side == "buy" and set_liq >= target:
            print(f"\n❌ 做多时设定强平线({set_liq})必须小于目标价格({target})，请重新配置。")
            return client

    print("\n" + "=" * 56)
    print("以下配置将用于定投做空，请确认")
    print("=" * 56)
    print(f"  合约      : {c['inst_id']}（{c['mgn_mode']}，{c['leverage']}x）")
    pm = c.get("price_mode", "same_1")
    pm_label = {"same_1": "同向价1", "same_5": "同向价5",
                "opposite_1": "对手价1", "opposite_5": "对手价5"}.get(pm, "同向价1")
    print(f"  下单      : 限价@{pm_label}  {c['amount_usdt']} USDT  ->  {c['side']}")
    print(f"  日期      : {t['start_date']} ~ {t['end_date']}（{t['date_type']}）")
    print(f"  定投时间  : {t['times']}")
    print(f"  设定强平线: {p.get('set_liq_px')}")
    print(f"  目标价格  : {p.get('target_px')}")
    print(f"  安全边际  : {p.get('safety_margin_pct')}%")
    try:
        bal = client.get_avail_bal()
        print(f"  可用余额  : {bal:.2f} USDT")
    except Exception:
        pass
    print("=" * 56)

    # 执行前让用户确认（仅 --run 无头模式跳过）
    if confirm:
        ans = menu_select("【请核对以上配置信息是否准确无误】", [
            ("确认无误，开始执行", "yes"),
            ("有误，返回主菜单重新配置", "no"),
        ], default="yes")
        if ans != "yes":
            print("  已返回主菜单，可重新配置。")
            return client
        print("  ✅ 配置确认无误，开始执行…\n")

    client.setup_account(cfg)
    client.run_loop(cfg)
    return client


# ---------------------------------------------------------------- 系统设置


def system_config(cfg):
    """系统设置：检测间隔、轮询间隔、重试参数等运行时参数。"""
    r = cfg["runtime"]
    monitor_opts = [
        ("30 秒（高杠杆灵敏）", "30"),
        ("60 秒（推荐）", "60"),
        ("2 分钟（多实例）", "120"),
        ("3 分钟", "180"),
        ("5 分钟（10+ 实例）", "300"),
        ("10 分钟", "600"),
    ]
    loop_opts = [
        ("10 秒", "10"),
        ("20 秒（推荐）", "20"),
        ("30 秒", "30"),
        ("60 秒", "60"),
    ]
    while True:
        current_monitor = r.get("monitor_interval_sec", 60)
        current_loop = r.get("interval_sec", 20)
        current_retry_max = r.get("retry_max", 5)
        current_retry_interval = r.get("retry_interval_sec", 1)
        current_fill_wait = r.get("fill_wait_sec", 300)
        choice = menu_select("系统设置", [
            (f"安全边际检测间隔（当前: {current_monitor}s）", "monitor"),
            (f"主循环轮询间隔（当前: {current_loop}s）", "loop"),
            (f"下单后等待成交超时（当前: {current_fill_wait}s）", "fill_wait"),
            (f"同向价挂单被拒重试次数（当前: {current_retry_max}次）", "retry_max"),
            (f"同向价挂单被拒重试间隔（当前: {current_retry_interval}s）", "retry_interval"),
            ("返回主菜单", "back"),
        ], default="back")

        if choice == "monitor":
            print("\n" + "-" * 56)
            print("安全边际检测间隔")
            print("-" * 56)
            print("脚本每隔这段时间检查一次「强平价与标记价的差距」，")
            print("判断两件事：")
            print("  · 差距是否跌破安全边际 → 暂停定投，推送警告")
            print("  · 差距是否在持续缩小 → 自动触发补仓\n")
            print("间隔越短，对行情变化越灵敏（高杠杆建议 30~60s），")
            print("但 API 请求频率也越高。如果你一台服务器跑多个实例，")
            print("适当拉长可以降低请求量。\n")
            print("推荐：单实例 30~60s，多实例 60~120s。")
            print("-" * 56)
            val = menu_select("请选择检测间隔", monitor_opts, default=str(current_monitor))
            r["monitor_interval_sec"] = int(val)
            save_config(cfg)
            print(f"  ✅ 安全边际检测间隔 = {val}s")
        elif choice == "loop":
            print("\n" + "-" * 56)
            print("主循环轮询间隔")
            print("-" * 56)
            print("脚本每隔这段时间检查一次「是否到了设定的定投时间点」。")
            print("因为定投只精确到分钟（如 10:00），所以这个间隔不需要")
            print("太短——只要在一分钟内能扫到就行。\n")
            print("注意：安全边际检测有自己独立的间隔（上一个选项），")
            print("不受此参数影响。\n")
            print("间隔越短，定投执行越准时，但 CPU 占用略高。")
            print("推荐 20s，平衡精度和资源。")
            print("-" * 56)
            val = menu_select("请选择轮询间隔", loop_opts, default=str(current_loop))
            r["interval_sec"] = int(val)
            save_config(cfg)
            print(f"  ✅ 主循环轮询间隔 = {val}s")
        elif choice == "fill_wait":
            print("\n" + "-" * 56)
            print("下单后等待成交超时")
            print("-" * 56)
            print("限价单提交后，脚本每秒轮询一次订单状态，等待订单成交。")
            print("同向价挂单本质是排队等对手盘来吃，不会立刻成交，所以需要")
            print("等足够久。超过这个时间还没成交，推送通知提醒手动处理。")
            print("重要：脚本是单线程串行执行，等待期间不会检测下一个定投时间点。")
            print("实际最大阻塞时间 ≈ 同向价被拒重试次数 × 重试间隔 + 等待超时，")
            print("两个定投时间点的间距应大于这个值，否则后面的时间点会被跳过。")
            print("比如设了 10:00 和 10:01，重试5次×1s+等待60s=65s，就会错过 10:01。")
            print("推荐 300 秒——给限价单足够的时间等对手盘来吃。")
            print("-" * 56)
            val = input_str("请输入等待超时（秒）", default=str(current_fill_wait))
            try:
                r["fill_wait_sec"] = max(int(val), 5)
            except ValueError:
                r["fill_wait_sec"] = 300
            save_config(cfg)
            print(f"  ✅ 等待成交超时 = {r['fill_wait_sec']}s")
        elif choice == "retry_max":
            print("\n" + "-" * 56)
            print("同向价挂单被拒重试次数")
            print("-" * 56)
            print("同向价（post_only）挂单时，如果盘口瞬间变化导致挂单价跨过")
            print("价差、被交易所立刻取消，脚本会自动重新读取最新盘口、重新")
            print("以同向价挂单，直到成交或次数用完。")
            print("设为 0 表示不重试，被拒直接推送通知让你手动处理。")
            print("推荐 5 次，覆盖绝大部分瞬时波动。")
            print("-" * 56)
            val = input_str("请输入重试次数", default=str(current_retry_max))
            try:
                r["retry_max"] = max(int(val), 0)
            except ValueError:
                r["retry_max"] = 5
            save_config(cfg)
            print(f"  ✅ 重试次数 = {r['retry_max']}")
        elif choice == "retry_interval":
            print("\n" + "-" * 56)
            print("同向价挂单被拒重试间隔")
            print("-" * 56)
            print("每次重试之间等待的时间。让盘口有一个短暂的稳定窗口，")
            print("避免刚被拒就立刻用同一个波动的价格再次挂单又被拒。")
            print("同时也避免频繁请求 OKX API 触发限流。")
            print("推荐 1 秒。")
            print("-" * 56)
            val = input_str("请输入重试间隔（秒）", default=str(current_retry_interval))
            try:
                r["retry_interval_sec"] = max(float(val), 0.5)
            except ValueError:
                r["retry_interval_sec"] = 1
            save_config(cfg)
            print(f"  ✅ 重试间隔 = {r['retry_interval_sec']}s")
        else:
            return


# ---------------------------------------------------------------- 主菜单

def main_menu(cfg, client):
    while True:
        status = "（已登录）" if client else "（未登录）"
        choice = menu_select("主菜单" + status, [
            ("执行策略", "run"),
            ("合约配置", "contract"),
            ("时间配置", "time"),
            ("暂停配置", "pause"),
            ("推送配置", "notify"),
            ("系统设置", "system"),
            ("定投统计", "stats"),
            ("重新登陆", "login"),
            ("退出", "exit"),
        ], default="run")
        if choice == "run":
            client = run_strategy(cfg, client)
        elif choice == "contract":
            contract_config(cfg)
        elif choice == "time":
            time_config(cfg)
        elif choice == "pause":
            pause_config(cfg)
        elif choice == "notify":
            push_config(cfg)
        elif choice == "system":
            system_config(cfg)
        elif choice == "stats":
            from stats import tracker
            print("\n" + tracker.summary())
            input("\n按回车返回主菜单…")
        elif choice == "login":
            client = login(cfg)
        else:
            print("程序正在准备退出...")
            return


def _setup_console():
    """保证中文在 Windows 控制台正常显示（UTF-8）。"""
    if sys.platform == "win32":
        try:
            import subprocess
            subprocess.run(["chcp", "65001"], shell=True, capture_output=True)
        except Exception:
            pass
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def run_headless(cfg):
    """无头模式：跳过菜单，直接用已保存配置启动定投（服务器 systemd/nohup 用）。"""
    if not cfg["api"].get("api_key"):
        print("❌ 未配置登录信息。请先交互运行一次 `python main.py` 完成登录与配置。")
        return
    client = build_client(cfg)
    run_strategy(cfg, client, confirm=False)


LOGO = r"""
  ██████╗ ████████╗███████╗██╗  ██╗
  ██╔══██╗╚══██╔══╝╚══███╔╝██║ ██╔╝
  ██║  ██║   ██║     ███╔╝ █████╔╝
  ██║  ██║   ██║    ███╔╝  ██╔═██╗
  ██████╔╝   ██║   ███████╗██║  ██╗
  ╚═════╝    ╚═╝   ╚══════╝╚═╝  ╚═╝
    定投做空 · Dollar-Cost Averaging Short  v1.2

    作者：梦中分解与AI助手dsv4
    此脚本完全免费，旨在帮助喜欢做模式外的家人们管住手降低赌性
    希望牧原🐷🐷一路长红，豆家军大获全胜
    如有bug联系QQ 2334947006
"""


def main():
    _setup_console()
    print(LOGO)
    setup_logging()
    cfg = load_config()

    # 无头模式：python main.py --run
    if "--run" in sys.argv:
        run_headless(cfg)
        return

    client = None
    if not cfg["api"].get("api_key"):
        # 首次运行自动进入登录
        client = login(cfg)
    else:
        print(f"\n检测到已保存的登录信息（环境: {'模拟盘' if cfg['api']['flag'] == '1' else '实盘'}）。")
        try:
            again = input("  直接进入主菜单吗？(回车=是 / 输入任意字符=重新登陆): ").strip()
        except EOFError:
            again = ""
        if again == "":
            client = build_client(cfg)   # 用已保存凭证进入（已登录）
        else:
            client = login(cfg)
    main_menu(cfg, client)


if __name__ == "__main__":
    try:
        main()
    except (KeyboardInterrupt, UnicodeDecodeError):
        print("\n程序正在准备退出...")
        sys.exit(0)
    except Exception as e:
        print(f"\n程序异常退出: {e}")
        _safe_msg = str(e).encode("ascii", errors="replace").decode("ascii")
        try:
            from notifier import Notifier
            _cfg = load_config()
            n = Notifier(_cfg.get("notify", {}))
            if n.enabled:
                n.send("dtzk 异常退出", f"脚本因异常崩溃退出：\n{_safe_msg}")
        except Exception:
            pass
        sys.exit(1)
