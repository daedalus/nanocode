"""Tests for main.py CLI arguments."""

from unittest.mock import patch

import pytest


class TestParseArgs:
    """Test argument parsing."""

    def test_proxy_argument(self):
        """Test --proxy argument is parsed correctly."""
        import sys

        from nanocode.main import parse_args

        with patch.object(sys, "argv", ["main.py", "--proxy", "http://localhost:8080"]):
            args = parse_args()
            assert args.proxy == "http://localhost:8080"

    def test_proxy_argument_none(self):
        """Test --proxy defaults to None when not provided."""
        import sys

        from nanocode.main import parse_args

        with patch.object(sys, "argv", ["main.py"]):
            args = parse_args()
            assert args.proxy is None

    def test_no_proxy_argument(self):
        """Test --no-proxy argument is parsed correctly."""
        import sys

        from nanocode.main import parse_args

        with patch.object(sys, "argv", ["main.py", "--no-proxy"]):
            args = parse_args()
            assert args.no_proxy is True


if __name__ == "__main__":
    pytest.main([__file__])
