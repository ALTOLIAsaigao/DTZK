# -*- coding: utf-8 -*-
"""
config.py —— 配置持久化模块

保存 / 读取定投做空脚本的全部配置到 config.json：
  - api    : OKX API 凭证（APIKey / SecretKey / Passphrase / flag）
  - contract: 合约配置（文档 1~7）
  - time   : 时间配置（文档 8~9）
  - pause  : 暂停与提醒配置（文档 10~12）
"""
import json
import os
import sys
from datetime import datetime


def _app_dir():
    """程序所在目录：打包成 exe 后返回 exe 所在目录（config.json 放在 exe 旁边）。"""
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


BASE_DIR = _app_dir()
CONFIG_PATH = os.path.join(BASE_DIR, "config.json")

DEFAULT_CONFIG = {
    "api": {
        "api_key": "",
        "secret_key": "",
        "passphrase": "",
        "flag": "1",          # "1"=模拟盘, "0"=实盘
    },
    "contract": {
        "inst_id": "BTC-USDT-SWAP",   # 1. 合约
        "mgn_mode": "isolated",       # 2. 逐仓 isolated / 全仓 cross
        "leverage": "1",              # 3. 杠杆，默认 1x
        "order_type": "post_only",    # 4. 默认；同向价自动post_only，对手价自动limit
        "price_mode": "same_1",        # 5. 委托价格：same_1/same_5/opposite_1/opposite_5
        "amount_usdt": "50",          # 6. 下单数量，单位 USDT
        "side": "sell",               # 7. 买入 buy / 卖出 sell（做空=卖出）
    },
    "time": {
        "start_date": "",             # 8. 开始日期 YYYY-MM-DD
        "end_date": "",               # 8. 结束日期 YYYY-MM-DD
        "date_type": "everyday",      # 9. 日期类型: everyday=期间每天 / weekday=工作日(周一至周五)
        "times": ["10:00"],           # 9. 每天定投的具体时间列表 HH:MM
    },
    "pause": {
        "set_liq_px": None,           # 10. 设定强平线（null=不启用自动补保证金）
        "target_px": None,            # 12. 目标价格（标记价 <= 目标价 时停止并退出）
        "safety_margin_pct": 0.0,     # 11. 安全边际 X%（强平价与标记价差距小于 X% 时暂停）
    },
    "notify": {
        "enabled": True,              # 是否启用手机推送（channel=none 时自然无效）
        "channel": "none",            # none / serverchan / pushplus / bark / telegram
        "serverchan_key": "",         # Server酱 SendKey（sct.ftqq.com 注册）
        "pushplus_token": "",         # PushPlus token（pushplus.plus 注册）
        "bark_url": "",               # Bark 推送地址（如 https://api.day.app/你的设备key）
        "telegram_bot_token": "",     # Telegram Bot Token
        "telegram_chat_id": "",       # Telegram Chat ID
    },
    "runtime": {
        "interval_sec": 20,           # 主循环轮询间隔（秒）
        "monitor_interval_sec": 60,   # 安全边际检测间隔（秒），独立于定投时间点
        "monitor_sec": 30,            # 暂停监控轮询间隔（秒）
        "fill_wait_sec": 300,         # 下单后等待成交确认的最长秒数
        "retry_max": 5,               # post_only被拒后自动重试次数
        "retry_interval_sec": 1,      # 每次重试间隔（秒）
        "timezone": "Asia/Shanghai",  # 定投执行时区（服务器可能为 UTC，务必确认）
        "log_file": "dtzk.log",       # 运行日志文件
        "proxy": "",                  # 代理地址，如 http://127.0.0.1:7890（本地Clash）或
                                      # http://服务器代理IP:端口（国内服务器连OKX必须配代理）
    },
}


def _normalize_times(cfg):
    """把定投时间统一规范化为 'HH:MM'（如 '3:43' -> '03:43'），防止匹配错位。"""
    times = cfg.get("time", {}).get("times")
    if times:
        norm = []
        for t in times:
            try:
                norm.append(datetime.strptime(str(t), "%H:%M").strftime("%H:%M"))
            except (ValueError, TypeError):
                norm.append(str(t))
        cfg["time"]["times"] = sorted(set(norm))
    return cfg


def load_config():
    """从 config.json 读取配置；不存在或损坏则返回默认配置。"""
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            # 用默认配置兜底，防止旧配置缺字段
            merged = _merge(DEFAULT_CONFIG, data)
            return _normalize_times(merged)
        except (json.JSONDecodeError, OSError):
            return _deep_copy(DEFAULT_CONFIG)
    return _deep_copy(DEFAULT_CONFIG)


def save_config(cfg):
    """把配置写回 config.json。"""
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)


def _merge(defaults, override):
    """递归合并：defaults 是骨架，override 里的值覆盖同名键。"""
    result = _deep_copy(defaults)
    if not isinstance(override, dict):
        return result
    for k, v in override.items():
        if k in result and isinstance(result[k], dict) and isinstance(v, dict):
            result[k] = _merge(result[k], v)
        else:
            result[k] = v
    return result


def _deep_copy(obj):
    return json.loads(json.dumps(obj))
