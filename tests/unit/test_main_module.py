"""Tests for __main__.py module entry point.

Uses subprocess to avoid the module-level sys.stdout reconfiguration
that interferes with pytest's capture mechanism.
"""

import subprocess
import sys


class TestCliMain:
    """Test cli_main entry point via subprocess."""

    def test_cli_main_imports_and_returns_exit_code(self):
        """Test that __main__ can be imported and cli_main returns an int."""
        code = (
            "import asyncio\n"
            "from unittest.mock import patch\n"
            "with patch('nanocode.__main__.main', return_value=0):\n"
            "    from nanocode.__main__ import cli_main\n"
            "    result = cli_main()\n"
            "    assert result == 0, f'Expected 0, got {result}'\n"
            "print('OK')\n"
        )
        result = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, f"stderr: {result.stderr}"
        assert "OK" in result.stdout

    def test_cli_main_returns_custom_exit_code(self):
        """Test cli_main returns the exit code from main()."""
        code = (
            "import asyncio\n"
            "from unittest.mock import patch\n"
            "with patch('nanocode.__main__.main', return_value=42):\n"
            "    from nanocode.__main__ import cli_main\n"
            "    result = cli_main()\n"
            "    assert result == 42, f'Expected 42, got {result}'\n"
            "print('OK')\n"
        )
        result = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, f"stderr: {result.stderr}"
        assert "OK" in result.stdout

    def test_module_runs_as_main(self):
        """Test that __main__ runs as __main__ and calls cli_main."""
        code = (
            "import sys\n"
            "sys.modules['nanocode'] = type(sys)('nanocode')\n"
            "sys.modules['nanocode'].__path__ = []\n"
            "print('module loaded')\n"
        )
        result = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
