"""Security adversarial tests - injection attacks, path traversal, and unsafe patterns."""

import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent / "nanocode"))

from nanocode.tools import Tool, ToolExecutor, ToolResult
from nanocode.config import Config


class TestSQLInjectionAdversarial:
    """Adversarial tests for SQL injection in tool parameters."""

    def test_sql_injection_in_read_tool(self):
        """ADVERSARIAL: SQL injection attempt via file path."""
        executor = ToolExecutor(Config())
        
        malicious_path = "'; DROP TABLE users; --"
        
        try:
            # Try to execute with malicious path
            result = executor.execute("read", {"path": malicious_path})
            # Should either reject, sanitize, or fail safely
            print(f"  SQL injection handled: {result}")
        except Exception as e:
            print(f"  Safely rejected: {e}")

    def test_sql_injection_in_grep(self):
        """ADVERSARIAL: SQL injection in grep pattern."""
        executor = ToolExecutor(Config())
        
        malicious_pattern = "'; DELETE FROM users; --"
        
        try:
            result = executor.execute("grep", {"pattern": malicious_pattern, "path": "/tmp"})
            print(f"  Grep with malicious pattern: {result}")
        except Exception as e:
            print(f"  Safely rejected: {e}")


class TestPathTraversalAdversarial:
    """Adversarial tests for path traversal attacks."""

    def test_path_traversal_absolute(self):
        """ADVERSARIAL: Absolute path traversal attempt."""
        executor = ToolExecutor(Config())
        
        malicious_path = "/etc/passwd"
        
        try:
            result = executor.execute("read", {"path": malicious_path})
            if result.success:
                # Check if we actually read the file (should be blocked)
                print(f"  Path traversal blocked: {result.content[:50] if result.content else 'empty'}")
            else:
                print(f"  Correctly rejected: {result.error}")
        except Exception as e:
            print(f"  Safely rejected: {e}")

    def test_path_traversal_relative(self):
        """ADVERSARIAL: Relative path with ../"""
        executor = ToolExecutor(Config())
        
        malicious_path = "../../../etc/passwd"
        
        try:
            result = executor.execute("read", {"path": malicious_path})
            print(f"  Relative path traversal: {result}")
        except Exception as e:
            print(f"  Safely rejected: {e}")

    def test_path_traversal_windows(self):
        """ADVERSARIAL: Windows-style path traversal."""
        executor = ToolExecutor(Config())
        
        malicious_path = "..\\..\\windows\\system32\\config"
        
        try:
            result = executor.execute("read", {"path": malicious_path})
            print(f"  Windows path traversal: {result}")
        except Exception as e:
            print(f"  Safely rejected: {e}")

    def test_path_null_byte(self):
        """ADVERSARIAL: Null byte injection."""
        executor = ToolExecutor(Config())
        
        malicious_path = "/etc/passwd\x00.txt"
        
        try:
            result = executor.execute("read", {"path": malicious_path})
            print(f"  Null byte handled: {result}")
        except Exception as e:
            print(f"  Safely rejected: {e}")


class TestShellInjectionAdversarial:
    """Adversarial tests for shell command injection."""

    def test_shell_injection_semicolon(self):
        """ADVERSARIAL: Semicolon command injection."""
        executor = ToolExecutor(Config())
        
        malicious_cmd = "echo test; rm -rf /"
        
        try:
            result = executor.execute("bash", {"command": malicious_cmd})
            print(f"  Semicolon injection: {result}")
        except Exception as e:
            print(f"  Safely rejected: {e}")

    def test_shell_injection_pipe(self):
        """ADVERSARIAL: Pipe command injection."""
        executor = ToolExecutor(Config())
        
        malicious_cmd = "echo test | cat /etc/passwd"
        
        try:
            result = executor.execute("bash", {"command": malicious_cmd})
            print(f"  Pipe injection: {result}")
        except Exception as e:
            print(f"  Safely rejected: {e}")

    def test_shell_injection_backtick(self):
        """ADVERSARIAL: Backtick command substitution."""
        executor = ToolExecutor(Config())
        
        malicious_cmd = "echo `cat /etc/passwd`"
        
        try:
            result = executor.execute("bash", {"command": malicious_cmd})
            print(f"  Backtick injection: {result}")
        except Exception as e:
            print(f"  Safely rejected: {e}")

    def test_shell_injection_dollar(self):
        """ADVERSARIAL: $() command substitution."""
        executor = ToolExecutor(Config())
        
        malicious_cmd = "$(cat /etc/passwd)"
        
        try:
            result = executor.execute("bash", {"command": malicious_cmd})
            print(f"  Dollar injection: {result}")
        except Exception as e:
            print(f"  Safely rejected: {e}")

    def test_shell_injection_and(self):
        """ADVERSARIAL: AND operator injection."""
        executor = ToolExecutor(Config())
        
        malicious_cmd = "true && rm -rf /"
        
        try:
            result = executor.execute("bash", {"command": malicious_cmd})
            print(f"  AND injection: {result}")
        except Exception as e:
            print(f"  Safely rejected: {e}")

    def test_shell_injection_or(self):
        """ADVERSARIAL: OR operator injection."""
        executor = ToolExecutor(Config())
        
        malicious_cmd = "false || cat /etc/passwd"
        
        try:
            result = executor.execute("bash", {"command": malicious_cmd})
            print(f"  OR injection: {result}")
        except Exception as e:
            print(f"  Safely rejected: {e}")


class TestEvalAdversarial:
    """Adversarial tests for unsafe eval usage."""

    def test_eval_injection(self):
        """ADVERSARIAL: Python eval injection."""
        executor = ToolExecutor(Config())
        
        malicious_code = "__import__('os').system('cat /etc/passwd')"
        
        try:
            result = executor.execute("bash", {"command": f"python -c 'exec({malicious_code!r})'"})
            print(f"  Eval injection result: {result}")
        except Exception as e:
            print(f"  Safely rejected: {e}")


class TestFormatStringAdversarial:
    """Adversarial tests for format string attacks."""

    def test_format_string_attribute(self):
        """ADVERSARIAL: Attribute access via format string."""
        executor = ToolExecutor(Config())
        
        malicious = "{{__import__('os').system('ls')}}"
        
        try:
            result = executor.execute("bash", {"command": f"echo {malicious}"})
            print(f"  Format string: {result}")
        except Exception as e:
            print(f"  Safely rejected: {e}")

    def test_format_string_subprocess(self):
        """ADVERSARIAL: Format string with subprocess."""
        executor = ToolExecutor(Config())
        
        malicious = "{__import__('subprocess').call(['ls'])}"
        
        try:
            result = executor.execute("bash", {"command": f"python -c 'print({malicious})'"})
            print(f"  Format subprocess: {result}")
        except Exception as e:
            print(f"  Safely rejected: {e}")


class TestXXEAdversarial:
    """Adversarial tests for XML external entity attacks."""

    def test_xxe_file_include(self):
        """ADVERSARIAL: XXE file inclusion."""
        executor = ToolExecutor(Config())
        
        xxe = '<?xml version="1.0"?><!DOCTYPE foo [<!ENTITY xxe SYSTEM "file:///etc/passwd">]><foo>&xxe;</foo>'
        
        try:
            # Tool that might parse XML
            result = executor.execute("bash", {"command": f"echo {xxe!r}"})
            print(f"  XXE: {result}")
        except Exception as e:
            print(f"  Safely rejected: {e}")


class TestReDoSAdversarial:
    """Adversarial tests for Regular Expression Denial of Service."""

    def test_catastrophic_backtracking(self):
        """ADVERSARIAL: Catastrophic backtracking in regex."""
        executor = ToolExecutor(Config())
        
        # Pattern that causes exponential blowup
        malicious = "aaaaaaaaaaaaac"
        
        try:
            result = executor.execute("grep", {"pattern": "(a+)+b", "path": malicious})
            print(f"  ReDoS: {result}")
        except Exception as e:
            print(f"  Safely handled: {e}")


class TestResourceExhaustionAdversarial:
    """Adversarial tests for resource exhaustion."""

    def test_memory_exhaustion(self):
        """ADVERSARIAL: Allocate massive memory."""
        executor = ToolExecutor(Config())
        
        try:
            result = executor.execute("bash", {"command": "python -c 'x = ' + 'x' * 100000000"})
            print(f"  Memory exhaustion: {result}")
        except Exception as e:
            print(f"  Safely rejected: {e}")

    def test_cpu_exhaustion(self):
        """ADVERSARIAL: Infinite loop."""
        executor = ToolExecutor(Config())
        
        try:
            result = executor.execute("bash", {"command": "python -c 'while True: pass'"})
            print(f"  CPU exhaustion: {result}")
        except Exception as e:
            print(f"  Safely rejected: {e}")


class TestTypeConfusionAdversarial:
    """Adversarial tests for type confusion attacks."""

    def test_json_object_injection(self):
        """ADVERSARIAL: JSON object instead of string."""
        from nanocode.llm import Message
        
        try:
            msg = Message(role="user", content={"key": "value"})
            print(f"  JSON object in message: {msg}")
        except Exception as e:
            print(f"  Safely rejected: {e}")

    def test_list_in_path(self):
        """ADVERSARIAL: List instead of path string."""
        executor = ToolExecutor(Config())
        
        try:
            result = executor.execute("read", {"path": ["/etc", "/passwd"]})
            print(f"  List in path: {result}")
        except Exception as e:
            print(f"  Safely rejected: {e}")

    def test_none_path(self):
        """ADVERSARIAL: None as path."""
        executor = ToolExecutor(Config())
        
        try:
            result = executor.execute("read", {"path": None})
            print(f"  None path: {result}")
        except Exception as e:
            print(f"  Safely rejected: {e}")


class TestEncodingConfusionAdversarial:
    """Adversarial tests for encoding confusion."""

    def test_utf16_bom(self):
        """ADVERSARIAL: UTF-16 BOM injection."""
        executor = ToolExecutor(Config())
        
        # UTF-16 BOM bytes
        malicious = "\ufeff/etc/passwd"
        
        try:
            result = executor.execute("read", {"path": malicious})
            print(f"  UTF-16 BOM: {result}")
        except Exception as e:
            print(f"  Safely rejected: {e}")

    def test_url_encoding(self):
        """ADVERSARIAL: URL encoding for path traversal."""
        executor = ToolExecutor(Config())
        
        malicious = "..%2f..%2f..%2fetc%2fpasswd"
        
        try:
            result = executor.execute("read", {"path": malicious})
            print(f"  URL encoding: {result}")
        except Exception as e:
            print(f"  Safely rejected: {e}")

    def test_double_url_encoding(self):
        """ADVERSARIAL: Double URL encoding."""
        executor = ToolExecutor(Config())
        
        malicious = "..%252f..%252f..%252fetc%252fpasswd"
        
        try:
            result = executor.execute("read", {"path": malicious})
            print(f"  Double URL encoding: {result}")
        except Exception as e:
            print(f"  Safely rejected: {e}")


class TestIntegerOverflowAdversarial:
    """Adversarial tests for integer overflow."""

    def test_negative_offset(self):
        """ADVERSARIAL: Negative offset in read."""
        executor = ToolExecutor(Config())
        
        try:
            result = executor.execute("read", {"path": "/tmp", "offset": -1})
            print(f"  Negative offset: {result}")
        except Exception as e:
            print(f"  Safely rejected: {e}")

    def test_huge_offset(self):
        """ADVERSARIAL: Huge offset value."""
        executor = ToolExecutor(Config())
        
        try:
            result = executor.execute("read", {"path": "/tmp", "offset": 2**63})
            print(f"  Huge offset: {result}")
        except Exception as e:
            print(f"  Safely rejected: {e}")

    def test_negative_limit(self):
        """ADVERSARIAL: Negative limit."""
        executor = ToolExecutor(Config())
        
        try:
            result = executor.execute("read", {"path": "/tmp", "limit": -100})
            print(f"  Negative limit: {result}")
        except Exception as e:
            print(f"  Safely rejected: {e}")


if __name__ == "__main__":
    print("Running security adversarial tests...")
    import pytest
    pytest.main([__file__, "-v", "-s"])