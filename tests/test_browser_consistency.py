import subprocess
import sys
from pathlib import Path

import pytest

from architecture_diagram.capture import _browser_path, _node_playwright


ROOT = Path(__file__).resolve().parents[1]


def test_interactive_architecture_browser_matrix():
    if not _node_playwright() or not _browser_path(None):
        pytest.skip("需要本机 Node Playwright 与 Chromium/Chrome")
    completed = subprocess.run([sys.executable, str(ROOT / "tests/browser_consistency.py")],
                               cwd=ROOT, capture_output=True, text=True, timeout=300)
    output = completed.stdout + "\n" + completed.stderr
    if completed.returncode and "ERR_NETWORK_ACCESS_DENIED" in output:
        pytest.skip("当前沙箱禁止 Playwright 访问本地 HTTP 回环；file:// Chromium 矩阵由独立测试覆盖")
    assert completed.returncode == 0, output
