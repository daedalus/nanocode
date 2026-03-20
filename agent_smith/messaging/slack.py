"""Slack messaging platform integration."""

import os
import asyncio
import logging
from typing import Any

from nanocode.messaging import MessagingPlatform, Message

logger = logging.getLogger(__name__)


class SlackPlatform(MessagingPlatform):
    """Slack messaging platform integration using Slack SDK."""

    def __init__(self, config: dict = None):
        super().__init__(config)
        self.bot_token = self.config.get("bot_token") or os.getenv("SLACK_BOT_TOKEN")
        self.signing_secret = self.config.get("signing_secret") or os.getenv("SLACK_SIGNING_SECRET")
        self.app_token = self.config.get("app_token") or os.getenv("SLACK_APP_TOKEN")
        self.socket_mode = self.config.get("socket_mode", True)
        self.client = None
        self.app = None
        self.sessions: dict[str, Any] = {}

    async def start(self):
        """Start the Slack bot."""
        try:
            from slack_bolt import App
            from slack_bolt.adapter.socket_mode import SocketModeHandler
        except ImportError:
            logger.warning("slack_bolt not installed. Install with: pip install slack-bolt")
            return

        self.app = App(
            token=self.bot_token,
            signing_secret=self.signing_secret,
            socket_mode=self.socket_mode,
            app_token=self.app_token,
        )

        self.app.message(self._handle_slack_message)
        self.app.command("/test", self._handle_test_command)

        if self.socket_mode:
            handler = SocketModeHandler(self.app, self.app_token)
            asyncio.create_task(self._run_handler(handler))
        else:
            await self.app.start()

        logger.info("Slack bot started")

    async def _run_handler(self, handler):
        """Run the socket mode handler."""
        try:
            handler.start()
        except Exception as e:
            logger.error(f"Slack handler error: {e}")

    async def _handle_slack_message(self, message, say, client):
        """Handle incoming Slack messages."""
        if message.get("subtype"):
            return

        text = message.get("text", "")
        if not text:
            return

        channel = message["channel"]
        thread = message.get("thread_ts", message["ts"])
        user = message["user"]
        session_key = f"{channel}-{thread}"

        msg = Message(
            text=text,
            user_id=user,
            chat_id=channel,
            message_id=message["ts"],
            thread_id=thread,
            raw=message,
        )

        self.sessions[session_key] = {
            "channel": channel,
            "thread": thread,
            "user": user,
        }

        response = await self.handle_message(msg)
        if response:
            await say({"text": response, "thread_ts": thread})

    async def _handle_test_command(self, command, ack, say):
        """Handle /test command."""
        await ack()
        await say("Bot is working!")

    async def stop(self):
        """Stop the Slack bot."""
        if self.app:
            try:
                self.app.stop()
            except Exception:
                pass
        logger.info("Slack bot stopped")

    async def send_message(self, chat_id: str, text: str, thread_id: str = None) -> str:
        """Send a message to a Slack channel."""
        if not self.app:
            return ""

        try:
            result = await self.app.client.chat_postMessage(
                channel=chat_id,
                text=text,
                thread_ts=thread_id,
            )
            return result.get("ts", "")
        except Exception as e:
            logger.error(f"Slack send error: {e}")
            return ""

    async def send_interactive_message(self, chat_id: str, text: str, buttons: list = None) -> str:
        """Send a message with interactive buttons to Slack."""
        if not self.app or not buttons:
            return await self.send_message(chat_id, text)

        blocks = [
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": text},
            },
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": btn.get("text", "")},
                        "value": btn.get("value", ""),
                        "action_id": btn.get("action_id", ""),
                    }
                    for btn in buttons
                ],
            },
        ]

        try:
            result = await self.app.client.chat_postMessage(
                channel=chat_id,
                text=text,
                blocks=blocks,
            )
            return result.get("ts", "")
        except Exception as e:
            logger.error(f"Slack interactive send error: {e}")
            return ""


def create_slack_platform(config: dict = None) -> SlackPlatform:
    """Factory function to create a Slack platform."""
    return SlackPlatform(config)
