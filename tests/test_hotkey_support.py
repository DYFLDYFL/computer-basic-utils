from unittest import TestCase, main

from file_organizer.hotkey_support import (
    DEFAULT_SCREENSHOT_HOTKEY,
    normalize_hotkey,
    validate_hotkey,
)


class HotkeySupportTest(TestCase):
    def test_normalize_hotkey_sorts_modifiers(self) -> None:
        self.assertEqual(normalize_hotkey("shift+ctrl+alt+s"), "ctrl+alt+shift+s")

    def test_validate_rejects_common_shortcut(self) -> None:
        with self.assertRaises(ValueError):
            validate_hotkey("ctrl+c")

    def test_default_hotkey_is_valid(self) -> None:
        self.assertEqual(validate_hotkey(DEFAULT_SCREENSHOT_HOTKEY), DEFAULT_SCREENSHOT_HOTKEY)


if __name__ == "__main__":
    main()
