# -*- coding: utf-8 -*-
"""
notifier.py —— 第三方手机推送

OKX API 没有给 App 发任意文字的接口，所以脚本里的自定义警告
（手动加保证金、暂停/恢复、目标价到达等）通过第三方渠道推到手机。

支持渠道（config.json -> notify.channel）：
  - serverchan : Server酱，免费推微信（sct.ftqq.com 注册拿 SendKey）
  - pushplus   : PushPlus，免费推微信（pushplus.plus 注册拿 token）
  - bark       : Bark，iPhone 专用（需自建或使用第三方 Bark 服务器，填完整推送地址）
  - telegram   : Telegram Bot

任何渠道发送失败只记日志，不影响主流程。
"""
import logging

import requests

logger = logging.getLogger("dtzk")


class Notifier:
    def __init__(self, cfg=None):
        self.cfg = cfg or {}

    @property
    def channel(self):
        return self.cfg.get("channel", "none")

    @property
    def enabled(self):
        return self.cfg.get("enabled", True) and self.channel != "none"

    def send(self, title, content):
        """发送通知（失败只记日志）。"""
        if not self.enabled:
            return
        ch = self.channel
        try:
            if ch == "serverchan":
                self._send_serverchan(title, content)
            elif ch == "pushplus":
                self._send_pushplus(title, content)
            elif ch == "bark":
                self._send_bark(title, content)
            elif ch == "telegram":
                self._send_telegram(title, content)
            else:
                return
            logger.info("已推送通知[%s]: %s", ch, title)
        except Exception as e:
            logger.warning("推送[%s]失败: %s", ch, e)

    def test(self):
        """发送一条测试消息，返回 (ok, 说明)。"""
        if not self.enabled:
            return False, "当前未配置推送渠道（channel=none），请先在菜单里选择一个渠道"
        self.send("OKX定投做空 · 测试", "这是一条测试通知，收到即表示配置成功 ✅")
        return True, f"已发送到 {self.channel}"

    # ---------------------------------------------------------- 各渠道实现

    def _send_serverchan(self, title, content):
        key = self.cfg.get("serverchan_key", "")
        if not key:
            raise ValueError("未配置 Server酱 SendKey")
        requests.post(
            f"https://sctapi.ftqq.com/{key}.send",
            data={"title": title, "desp": content}, timeout=10)

    def _send_pushplus(self, title, content):
        token = self.cfg.get("pushplus_token", "")
        if not token:
            raise ValueError("未配置 PushPlus token")
        requests.post(
            "https://www.pushplus.plus/send",
            json={"token": token, "title": title, "content": content}, timeout=10)

    def _send_bark(self, title, content):
        from urllib.parse import quote
        url = self.cfg.get("bark_url", "").rstrip("/")
        if not url:
            raise ValueError("未配置 Bark 推送地址（如 https://api.day.app/你的设备key）")
        requests.get(
            f"{url}/{quote(title)}/{quote(content)}", timeout=10)

    def _send_telegram(self, title, content):
        token = self.cfg.get("telegram_bot_token", "")
        chat = self.cfg.get("telegram_chat_id", "")
        if not token or not chat:
            raise ValueError("未配置 Telegram bot token / chat_id")
        requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat, "text": f"{title}\n{content}"}, timeout=10)
