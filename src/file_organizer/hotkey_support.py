from __future__ import annotations

import sys
from typing import Callable

DEFAULT_SCREENSHOT_HOTKEY = "ctrl+q"
DEFAULT_RECORD_HOTKEY = "ctrl+shift+r"
MODIFIER_ORDER = ("ctrl", "alt", "shift", "win")
ALLOWED_MODIFIERS = frozenset(MODIFIER_ORDER)
ALLOWED_KEYS = frozenset(
    {*(chr(code) for code in range(ord("a"), ord("z") + 1)),
     *(str(digit) for digit in range(10)),
     *(f"f{number}" for number in range(1, 13))}
)

RESERVED_HOTKEYS = frozenset(
    {
        "ctrl+a",
        "ctrl+c",
        "ctrl+f",
        "ctrl+n",
        "ctrl+o",
        "ctrl+p",
        "ctrl+s",
        "ctrl+t",
        "ctrl+v",
        "ctrl+w",
        "ctrl+x",
        "ctrl+y",
        "ctrl+z",
        "ctrl+tab",
        "alt+tab",
        "alt+f4",
        "shift+delete",
        "win",
        "win+d",
        "win+e",
        "win+l",
        "win+r",
        "win+tab",
    }
)


def normalize_hotkey(value: str) -> str:
    parts = [part.strip().lower() for part in value.replace("-", "+").split("+") if part.strip()]
    if not parts:
        raise ValueError("快捷键不能为空")

    modifiers: list[str] = []
    key: str | None = None
    for part in parts:
        if part == "control":
            part = "ctrl"
        if part in ALLOWED_MODIFIERS:
            if part not in modifiers:
                modifiers.append(part)
            continue
        if key is not None:
            raise ValueError("快捷键只能包含一个主键")
        key = part

    if key is None:
        raise ValueError("快捷键必须包含主键")
    if key not in ALLOWED_KEYS:
        raise ValueError(f"不支持的主键：{key}")
    if not modifiers:
        raise ValueError("全局快捷键必须包含 Ctrl、Alt、Shift 或 Win 修饰键")

    ordered_modifiers = [name for name in MODIFIER_ORDER if name in modifiers]
    return "+".join([*ordered_modifiers, key])


def validate_hotkey(value: str, *, require_keyboard: bool = True) -> str:
    if sys.platform != "win32":
        raise ValueError("快捷键仅支持 Windows")

    normalized = normalize_hotkey(value)
    if normalized in RESERVED_HOTKEYS:
        raise ValueError(f"该快捷键与常用系统快捷键冲突：{normalized}")

    if not require_keyboard:
        return normalized

    try:
        import keyboard
    except ImportError as error:
        raise ValueError("缺少 keyboard 库，无法注册全局快捷键") from error

    keyboard.parse_hotkey(normalized)
    return normalized


class GlobalHotkeyManager:
    def __init__(self, root, callback: Callable[[], None]) -> None:  # type: ignore[no-untyped-def]
        self.root = root
        self.callback = callback
        self._hotkey: str | None = None

    def register(self, hotkey: str) -> None:
        self.unregister()
        validated = validate_hotkey(hotkey)

        import keyboard

        keyboard.add_hotkey(validated, self._trigger, suppress=False)
        self._hotkey = validated

    def unregister(self) -> None:
        if self._hotkey is None:
            return

        import keyboard

        try:
            keyboard.remove_hotkey(self._hotkey)
        except KeyError:
            pass
        self._hotkey = None

    def _trigger(self) -> None:
        self.root.after(0, self.callback)
