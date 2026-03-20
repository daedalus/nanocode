"""Messaging integrations base classes."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Callable, Awaitable


@dataclass
class Message:
    """Represents a message from a messaging platform."""

    text: str
    user_id: str
    chat_id: str
    message_id: str = ""
    thread_id: str = ""
    raw: dict = None


@dataclass
class MessageContext:
    """Context for handling messages."""

    message: Message
    session_id: str = ""


class MessagingPlatform(ABC):
    """Abstract base class for messaging platform integrations."""

    def __init__(self, config: dict = None):
        self.config = config or {}
        self.handlers: dict[str, Callable] = {}

    @abstractmethod
    async def start(self):
        """Start the messaging platform listener."""
        pass

    @abstractmethod
    async def stop(self):
        """Stop the messaging platform listener."""
        pass

    @abstractmethod
    async def send_message(self, chat_id: str, text: str, thread_id: str = None) -> str:
        """Send a message to a chat. Returns message ID."""
        pass

    @abstractmethod
    async def send_interactive_message(self, chat_id: str, text: str, buttons: list = None) -> str:
        """Send a message with interactive buttons."""
        pass

    def on_message(self, handler: Callable[[MessageContext], Awaitable[str]]):
        """Register a message handler."""
        self.handlers["message"] = handler

    def on_callback(self, handler: Callable[[str, str], Awaitable[str]]):
        """Register a callback handler for button clicks."""
        self.handlers["callback"] = handler

    async def handle_message(self, message: Message) -> str:
        """Handle an incoming message."""
        if "message" in self.handlers:
            ctx = MessageContext(message=message)
            return await self.handlers["message"](ctx)
        return ""

    async def handle_callback(self, callback_id: str, data: str) -> str:
        """Handle a callback (button click)."""
        if "callback" in self.handlers:
            return await self.handlers["callback"](callback_id, data)
        return ""


class MessagingManager:
    """Manages multiple messaging platform integrations."""

    def __init__(self):
        self.platforms: dict[str, MessagingPlatform] = {}

    def register(self, name: str, platform: MessagingPlatform):
        """Register a messaging platform."""
        self.platforms[name] = platform

    def get(self, name: str) -> MessagingPlatform:
        """Get a messaging platform by name."""
        return self.platforms.get(name)

    def list_platforms(self) -> list[str]:
        """List all registered platform names."""
        return list(self.platforms.keys())

    async def start_all(self):
        """Start all registered platforms."""
        for platform in self.platforms.values():
            await platform.start()

    async def stop_all(self):
        """Stop all registered platforms."""
        for platform in self.platforms.values():
            await platform.stop()


from nanocode.messaging.slack import SlackPlatform, create_slack_platform
from nanocode.messaging.telegram import TelegramPlatform, create_telegram_platform
from nanocode.messaging.whatsapp import WhatsAppPlatform, create_whatsapp_platform

__all__ = [
    "Message",
    "MessageContext",
    "MessagingPlatform",
    "MessagingManager",
    "SlackPlatform",
    "TelegramPlatform",
    "WhatsAppPlatform",
    "create_slack_platform",
    "create_telegram_platform",
    "create_whatsapp_platform",
]
