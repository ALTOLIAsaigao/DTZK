# -*- coding: utf-8 -*-
"""
menu.py —— 方向键选择菜单（↑/↓ 移动、回车确认、白底高亮）

跨平台：Windows / Linux(服务器SSH) / macOS 均可。
终端不可用（无 tty、PyCharm 未开终端模拟、questionary 缺失）时
自动退化为数字输入，保证脚本不会崩。

用法：
    from menu import select
    v = select("请选择：", [("选项A", "a"), ("选项B", "b")], default="a")
"""
import logging
import sys

logger = logging.getLogger("dtzk")

try:
    import questionary
    from prompt_toolkit.styles import Style
    _HAS_Q = True
except ImportError:
    questionary = None
    _HAS_Q = False

# 选中项白底高亮样式
_HL_STYLE = None
if _HAS_Q:
    _HL_STYLE = Style([
        ("selected", "bg:white fg:black bold"),
        ("pointer", "bg:white fg:black bold"),
        ("question", "bold"),
    ])


def _normalize(options):
    """把 list[(label, value)] 或 list[str] 统一成 list[(label, value)]。"""
    if not options:
        return []
    if all(isinstance(o, tuple) and len(o) == 2 for o in options):
        return [(str(l), v) for l, v in options]
    return [(str(o), o) for o in options]


def select(title, options, default=None):
    """方向键选择菜单，返回选中项的 value。

    title  : 菜单标题
    options: list[(显示文字, 返回值)] 或 list[str]
    default: 默认选中的 value（缺省选中第一项）
    """
    items = _normalize(options)
    if not items:
        return None
    labels = [l for l, _ in items]
    default_idx = 0
    if default is not None:
        for i, (_, v) in enumerate(items):
            if v == default:
                default_idx = i
                break

    # 主路径：方向键菜单（要求真实终端）
    if _HAS_Q and sys.stdin.isatty():
        try:
            choice = questionary.select(
                title, choices=labels,
                default=labels[default_idx], style=_HL_STYLE,
            ).ask()
            if choice is not None:
                for l, v in items:
                    if l == choice:
                        return v
            # 用户按 Esc 取消 -> 返回默认值
            return default if default is not None else items[default_idx][1]
        except KeyboardInterrupt:
            raise
        except Exception as e:
            logger.warning("方向键菜单不可用(%s)，退回数字输入", e)

    # 退化：数字输入（无终端 / 异常时兜底）
    print(title)
    for i, (label, _) in enumerate(items, 1):
        mark = "  <-- 当前" if i - 1 == default_idx else ""
        print(f"  {i}. {label}{mark}")
    while True:
        try:
            val = input(f"  请选择(1-{len(items)})，回车默认{default_idx + 1}: ").strip()
        except KeyboardInterrupt:
            raise
        except EOFError:
            val = ""
        if val == "":
            return items[default_idx][1]
        if val.isdigit() and 1 <= int(val) <= len(items):
            return items[int(val) - 1][1]
        print("  输入无效，请重新选择。")
