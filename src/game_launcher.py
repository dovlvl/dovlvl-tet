"""Open the official game in a separate Chrome app window."""
import os
import shutil
import subprocess
from pathlib import Path

GAME_URL = 'https://play.tetris.com/'


def chrome_path():
    candidates = [shutil.which('chrome.exe')]
    for name in ('PROGRAMFILES', 'PROGRAMFILES(X86)', 'LOCALAPPDATA'):
        base = os.environ.get(name)
        if base:
            candidates.append(str(Path(base) / 'Google/Chrome/Application/chrome.exe'))
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return candidate
    raise FileNotFoundError('Chrome을 찾지 못했습니다. Google Chrome 설치 후 다시 실행하세요.')


def open_game():
    # App mode leaves the game visible without the address bar or other tabs.
    # Use the existing Chrome profile; never change its settings or close tabs.
    return subprocess.Popen([chrome_path(), '--app='+GAME_URL,
                             '--window-size=800,760', '--window-position=20,20'])
