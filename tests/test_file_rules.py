from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase, main

from file_organizer import file_rules
from file_organizer.file_rules import (
    MANAGED_FOLDER_NAME,
    categorize_path,
    get_app_base_folder,
    is_internal_path,
    unique_destination,
)


class FileRulesTest(TestCase):
    def test_default_managed_folder_name_is_myfile(self) -> None:
        self.assertEqual(MANAGED_FOLDER_NAME, "myfile")

    def test_app_base_folder_uses_project_root_in_source_mode(self) -> None:
        expected_root = Path(file_rules.__file__).resolve().parents[2]
        self.assertEqual(get_app_base_folder(), expected_root)

    def test_categorize_path_uses_extension_groups(self) -> None:
        with TemporaryDirectory() as temp_dir:
            tmp_path = Path(temp_dir)
            document = tmp_path / "notes.pdf"
            image = tmp_path / "photo.JPG"
            unknown = tmp_path / "data.unknown"

            document.write_text("", encoding="utf-8")
            image.write_text("", encoding="utf-8")
            unknown.write_text("", encoding="utf-8")

            self.assertEqual(categorize_path(document), "Documents")
            self.assertEqual(categorize_path(image), "Images")
            self.assertEqual(categorize_path(unknown), "Other")

    def test_internal_paths_are_excluded(self) -> None:
        with TemporaryDirectory() as temp_dir:
            tmp_path = Path(temp_dir)
            source_file = tmp_path / "src" / "app.py"
            user_file = tmp_path / "report.txt"
            exe_file = tmp_path / "tool.exe"

            source_file.parent.mkdir()
            source_file.write_text("", encoding="utf-8")
            user_file.write_text("", encoding="utf-8")
            exe_file.write_text("", encoding="utf-8")

            self.assertTrue(is_internal_path(source_file, tmp_path))
            self.assertFalse(is_internal_path(user_file, tmp_path))
            self.assertFalse(is_internal_path(exe_file, tmp_path))

    def test_unique_destination_adds_counter(self) -> None:
        with TemporaryDirectory() as temp_dir:
            tmp_path = Path(temp_dir)
            existing = tmp_path / "file.txt"
            existing.write_text("", encoding="utf-8")

            self.assertEqual(unique_destination(existing), tmp_path / "file (1).txt")


if __name__ == "__main__":
    main()
