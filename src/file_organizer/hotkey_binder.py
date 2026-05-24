from __future__ import annotations

from typing import Callable

from .hotkey_support import normalize_hotkey, validate_hotkey


def hotkey_to_tk_sequence(hotkey: str) -> str:
    normalized = normalize_hotkey(hotkey)
    parts = normalized.split("+")
    key = parts[-1]
    modifiers = parts[:-1]
    tk_modifiers: list[str] = []
    for name in modifiers:
        if name == "ctrl":
            tk_modifiers.append("Control")
        elif name == "alt":
            tk_modifiers.append("Alt")
        elif name == "shift":
            tk_modifiers.append("Shift")
        elif name == "win":
            tk_modifiers.append("Win")

    if len(key) == 1:
        key_token = key.upper()
    elif key.startswith("f") and key[1:].isdigit():
        key_token = key.upper()
    else:
        key_token = key.capitalize()

    if tk_modifiers:
        return f"<{'-'.join(tk_modifiers)}-{key_token}>"
    return f"<{key_token}>"


class AppHotkeyBinder:
    def __init__(self, root) -> None:  # type: ignore[no-untyped-def]
        self.root = root
        self._global: dict[str, str] = {}
        self._local_sequences: dict[str, str] = {}

    def register(
        self,
        hotkey_id: str,
        hotkey: str,
        callback: Callable[[], None],
        *,
        global_enabled: bool,
    ) -> str:
        self.unregister(hotkey_id)
        normalized = validate_hotkey(hotkey, require_keyboard=global_enabled)

        if global_enabled:
            import keyboard

            keyboard.add_hotkey(normalized, callback, suppress=False)
            self._global[hotkey_id] = normalized
            return normalized

        sequence = hotkey_to_tk_sequence(normalized)

        def handler(_event) -> str:  # type: ignore[no-untyped-def]
            callback()
            return "break"

        self.root.bind(sequence, handler, add="+")
        self._local_sequences[hotkey_id] = sequence
        return normalized

    def unregister(self, hotkey_id: str) -> None:
        if hotkey_id in self._global:
            import keyboard

            try:
                keyboard.remove_hotkey(self._global[hotkey_id])
            except KeyError:
                pass
            del self._global[hotkey_id]

        if hotkey_id in self._local_sequences:
            self.root.unbind(self._local_sequences[hotkey_id])
            del self._local_sequences[hotkey_id]

    def unregister_all(self) -> None:
        for hotkey_id in list(self._global):
            self.unregister(hotkey_id)
        for hotkey_id in list(self._local_sequences):
            self.unregister(hotkey_id)
