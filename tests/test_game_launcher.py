import unittest
from unittest.mock import patch

import bootstrap  # noqa: F401 -- configure source imports
import game_launcher


class GameLauncherTests(unittest.TestCase):
    def test_launches_official_game_in_separate_window(self):
        with (
            patch.object(game_launcher, "chrome_path", return_value=r"C:\Chrome\chrome.exe"),
            patch.object(game_launcher.subprocess, "Popen") as launch,
        ):
            game_launcher.open_game()
        args = launch.call_args.args[0]
        self.assertEqual(args[0], r"C:\Chrome\chrome.exe")
        self.assertIn("--app=https://play.tetris.com/", args)
        self.assertIn("--window-size=800,760", args)

    def test_missing_chrome_reports_actionable_error(self):
        with (
            patch.object(game_launcher.shutil, "which", return_value=None),
            patch.object(game_launcher.Path, "is_file", return_value=False),
        ):
            with self.assertRaisesRegex(FileNotFoundError, "Chrome"):
                game_launcher.chrome_path()
