"""Telegram messaging platform integration."""

import os
import logging

from nanocode.messaging import MessagingPlatform, Message

logger = logging.getLogger(__name__)


class TelegramPlatform(MessagingPlatform):
    """Telegram messaging platform integration using python-telegram-bot."""

    def __init__(self, config: dict = None):
        super().__init__(config)
        self.bot_token = self.config.get("bot_token") or os.getenv("TELEGRAM_BOT_TOKEN")
        self.api = None
        self.application = None
        self.sessions: dict[str, dict] = {}

    async def start(self):
        """Start the Telegram bot."""
        try:
            from telegram import Update
            from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes
            from telegram.ext import filters
        except ImportError:
            logger.warning(
                "python-telegram-bot not installed. Install with: pip install python-telegram-bot"
            )
            return

        self.application = Application.builder().token(self.bot_token).build()

        self.application.add_handler(CommandHandler("start", self._start_command))
        self.application.add_handler(CommandHandler("help", self._help_command))
        self.application.add_handler(
            MessageHandler(filters.TEXT & ~filters.COMMAND, self._handle_message)
        )

        await self.application.run_polling(drop_pending_updates=True)
        logger.info("Telegram bot started")

    async def _start_command(self, update, context):
        """Handle /start command."""
        await update.message.reply_text(
            "Hello! I'm your AI assistant. Send me a message to get started."
        )

    async def _help_command(self, update, context):
        """Handle /help command."""
        await update.message.reply_text("Just send me a message and I'll respond!")

    async def _handle_message(self, update, context):
        """Handle incoming Telegram messages."""
        message = update.message
        if not message:
            return

        text = message.text
        if not text:
            return

        chat_id = str(message.chat.id)
        user_id = str(message.from_user.id)
        message_id = str(message.message_id)

        msg = Message(
            text=text,
            user_id=user_id,
            chat_id=chat_id,
            message_id=message_id,
            raw=message.to_dict(),
        )

        self.sessions[chat_id] = {
            "chat_id": chat_id,
            "user_id": user_id,
        }

        response = await self.handle_message(msg)
        if response:
            await context.bot.send_message(chat_id=chat_id, text=response)

    async def stop(self):
        """Stop the Telegram bot."""
        if self.application:
            await self.application.stop()
        logger.info("Telegram bot stopped")

    async def send_message(self, chat_id: str, text: str, thread_id: str = None) -> str:
        """Send a message to a Telegram chat."""
        if not self.application:
            return ""

        try:
            msg = await self.application.bot.send_message(chat_id=chat_id, text=text)
            return str(msg.message_id)
        except Exception as e:
            logger.error(f"Telegram send error: {e}")
            return ""

    async def send_interactive_message(self, chat_id: str, text: str, buttons: list = None) -> str:
        """Send a message with inline keyboard buttons to Telegram."""
        if not self.application or not buttons:
            return await self.send_message(chat_id, text)

        try:
            from telegram import InlineKeyboardButton, InlineKeyboardMarkup

            keyboard = [
                [InlineKeyboardButton(btn.get("text", ""), callback_data=btn.get("value", ""))]
                for btn in buttons
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)

            msg = await self.application.bot.send_message(
                chat_id=chat_id,
                text=text,
                reply_markup=reply_markup,
            )
            return str(msg.message_id)
        except Exception as e:
            logger.error(f"Telegram interactive send error: {e}")
            return ""


def create_telegram_platform(config: dict = None) -> TelegramPlatform:
    """Factory function to create a Telegram platform."""
    return TelegramPlatform(config)
