"""Tests for messaging platform integration base classes.

Import platform classes directly from their modules to avoid
circular imports caused by nanocode.messaging.__init__ importing
submodules that import from the parent.
"""

from unittest.mock import MagicMock, patch

import pytest


class TestMessage:
    """Test Message dataclass from nanocode.messaging."""

    def test_message_creation(self):
        """Test creating a Message."""
        from nanocode.messaging import Message as Msg

        msg = Msg(text="hello", user_id="user1", chat_id="chat1")
        assert msg.text == "hello"
        assert msg.user_id == "user1"
        assert msg.chat_id == "chat1"


class TestMessagingPlatform:
    """Test MessagingPlatform base class."""

    def _make_platform(self, config=None):
        """Create a concrete subclass of MessagingPlatform for testing."""
        from nanocode.messaging import MessagingPlatform

        class ConcretePlatform(MessagingPlatform):
            async def start(self):
                pass
            async def stop(self):
                pass
            async def send_message(self, chat_id, text, thread_id=None):
                return ""
            async def send_interactive_message(self, chat_id, text, buttons=None):
                return ""

        return ConcretePlatform(config=config)

    def test_init(self):
        """Test MessagingPlatform initialization."""
        from nanocode.messaging import MessagingPlatform

        platform = self._make_platform(config={"key": "value"})
        assert platform.config == {"key": "value"}
        assert platform.handlers == {}

    def test_on_message(self):
        """Test on_message registers handler."""
        from nanocode.messaging import MessagingPlatform

        platform = self._make_platform()
        handler = MagicMock()
        platform.on_message(handler)
        assert platform.handlers["message"] is handler

    @pytest.mark.asyncio
    async def test_handle_message(self):
        """Test handle_message calls registered handler."""
        from unittest.mock import AsyncMock
        from nanocode.messaging import Message as Msg

        platform = self._make_platform()
        handler = AsyncMock(return_value="response")
        platform.on_message(handler)
        msg = Msg(text="hello", user_id="user1", chat_id="chat1")
        result = await platform.handle_message(msg)
        assert result == "response"

    @pytest.mark.asyncio
    async def test_handle_message_no_handler(self):
        """Test handle_message returns empty when no handler."""
        from nanocode.messaging import Message as Msg

        platform = self._make_platform()
        msg = Msg(text="hello", user_id="user1", chat_id="chat1")
        result = await platform.handle_message(msg)
        assert result == ""

    @pytest.mark.asyncio
    async def test_handle_callback(self):
        """Test handle_callback calls registered handler."""
        from unittest.mock import AsyncMock

        platform = self._make_platform()
        handler = AsyncMock(return_value="response")
        platform.on_callback(handler)
        result = await platform.handle_callback("cb_1", "data")
        assert result == "response"

    @pytest.mark.asyncio
    async def test_handle_callback_no_handler(self):
        """Test handle_callback returns empty when no handler."""
        platform = self._make_platform()
        result = await platform.handle_callback("cb_1", "data")
        assert result == ""


class TestMessagingManager:
    """Test MessagingManager."""

    def _make_platform(self):
        from nanocode.messaging import MessagingPlatform

        class ConcretePlatform(MessagingPlatform):
            async def start(self):
                pass
            async def stop(self):
                pass
            async def send_message(self, chat_id, text, thread_id=None):
                return ""
            async def send_interactive_message(self, chat_id, text, buttons=None):
                return ""

        return ConcretePlatform()

    def test_register(self):
        """Test register adds a platform."""
        from nanocode.messaging import MessagingManager

        mgr = MessagingManager()
        platform = self._make_platform()
        mgr.register("test", platform)
        assert mgr.platforms["test"] is platform

    def test_list_platforms(self):
        """Test list_platforms returns registered names."""
        from nanocode.messaging import MessagingManager

        mgr = MessagingManager()
        mgr.register("a", self._make_platform())
        mgr.register("b", self._make_platform())
        names = mgr.list_platforms()
        assert "a" in names
        assert "b" in names


class TestSlackPlatform:
    """Test SlackPlatform (without external deps)."""

    def test_init(self):
        """Test SlackPlatform initialization."""
        from nanocode.messaging.slack import SlackPlatform

        platform = SlackPlatform({"bot_token": "xoxb-test"})
        assert platform.bot_token == "xoxb-test"

    def test_init_from_env(self):
        """Test SlackPlatform reads from env."""
        from nanocode.messaging.slack import SlackPlatform

        with patch.dict("os.environ", {"SLACK_BOT_TOKEN": "xoxb-env"}):
            platform = SlackPlatform()
            assert platform.bot_token == "xoxb-env"

    @pytest.mark.asyncio
    async def test_send_message_no_app(self):
        """Test send_message returns empty when not started."""
        from nanocode.messaging.slack import SlackPlatform

        platform = SlackPlatform()
        result = await platform.send_message("C123", "hello")
        assert result == ""

    def test_factory(self):
        """Test create_slack_platform factory."""
        from nanocode.messaging.slack import create_slack_platform, SlackPlatform

        platform = create_slack_platform({"bot_token": "xoxb-test"})
        assert isinstance(platform, SlackPlatform)


class TestTelegramPlatform:
    """Test TelegramPlatform (without external deps)."""

    def test_init(self):
        """Test TelegramPlatform initialization."""
        from nanocode.messaging.telegram import TelegramPlatform

        platform = TelegramPlatform({"bot_token": "123:ABC"})
        assert platform.bot_token == "123:ABC"

    def test_init_from_env(self):
        """Test TelegramPlatform reads from env."""
        from nanocode.messaging.telegram import TelegramPlatform

        with patch.dict("os.environ", {"TELEGRAM_BOT_TOKEN": "456:DEF"}):
            platform = TelegramPlatform()
            assert platform.bot_token == "456:DEF"

    @pytest.mark.asyncio
    async def test_send_message_no_app(self):
        """Test send_message returns empty when not started."""
        from nanocode.messaging.telegram import TelegramPlatform

        platform = TelegramPlatform()
        result = await platform.send_message("123", "hello")
        assert result == ""

    def test_factory(self):
        """Test create_telegram_platform factory."""
        from nanocode.messaging.telegram import create_telegram_platform, TelegramPlatform

        platform = create_telegram_platform({"bot_token": "123:ABC"})
        assert isinstance(platform, TelegramPlatform)


class TestWhatsAppPlatform:
    """Test WhatsAppPlatform (without external deps)."""

    def test_init(self):
        """Test WhatsAppPlatform initialization."""
        from nanocode.messaging.whatsapp import WhatsAppPlatform

        platform = WhatsAppPlatform({"phone_number_id": "123", "access_token": "token"})
        assert platform.phone_number_id == "123"
        assert platform.access_token == "token"

    def test_verify_signature_no_secret(self):
        """Test verify_signature returns True when no secret configured."""
        from nanocode.messaging.whatsapp import WhatsAppPlatform

        platform = WhatsAppPlatform()
        assert platform.verify_signature(b"payload", "signature") is True

    def test_verify_signature_valid(self):
        """Test verify_signature with valid signature."""
        import hmac, hashlib
        from nanocode.messaging.whatsapp import WhatsAppPlatform

        secret = "test-secret"
        payload = b"test-payload"
        sig = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
        platform = WhatsAppPlatform({"app_secret": secret})
        assert platform.verify_signature(payload, sig) is True

    @pytest.mark.asyncio
    async def test_send_message_no_creds(self):
        """Test send_message returns empty when not configured."""
        from nanocode.messaging.whatsapp import WhatsAppPlatform

        platform = WhatsAppPlatform()
        result = await platform.send_message("123", "hello")
        assert result == ""

    def test_factory(self):
        """Test create_whatsapp_platform factory."""
        from nanocode.messaging.whatsapp import create_whatsapp_platform, WhatsAppPlatform

        platform = create_whatsapp_platform({"phone_number_id": "123"})
        assert isinstance(platform, WhatsAppPlatform)
