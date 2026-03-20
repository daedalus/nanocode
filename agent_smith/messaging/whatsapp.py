"""WhatsApp messaging platform integration."""

import os
import logging
import hashlib
import hmac
from aiohttp import web

from nanocode.messaging import MessagingPlatform, Message

logger = logging.getLogger(__name__)


class WhatsAppPlatform(MessagingPlatform):
    """WhatsApp messaging platform integration using WhatsApp Cloud API."""

    def __init__(self, config: dict = None):
        super().__init__(config)
        self.phone_number_id = self.config.get("phone_number_id") or os.getenv(
            "WHATSAPP_PHONE_NUMBER_ID"
        )
        self.access_token = self.config.get("access_token") or os.getenv("WHATSAPP_ACCESS_TOKEN")
        self.verify_token = self.config.get("verify_token") or os.getenv(
            "WHATSAPP_VERIFY_TOKEN", "your_verify_token"
        )
        self.app_secret = self.config.get("app_secret") or os.getenv("WHATSAPP_APP_SECRET")
        self.webhook_port = self.config.get("webhook_port", 8080)
        self.app = None
        self.runner = None
        self.sessions: dict[str, dict] = {}

    async def start(self):
        """Start the WhatsApp webhook server."""
        self.app = web.Application()
        self.app.router.add_get("/webhook", self._webhook_get)
        self.app.router.add_post("/webhook", self._webhook_post)

        self.runner = web.AppRunner(self.app)
        await self.runner.setup()
        site = web.TCPSite(self.runner, "0.0.0.0", self.webhook_port)
        await site.start()
        logger.info(f"WhatsApp webhook server started on port {self.webhook_port}")

    async def _webhook_get(self, request):
        """Handle webhook verification from Meta."""
        mode = request.query.get("hub.mode")
        token = request.query.get("hub.verify_token")
        challenge = request.query.get("hub.challenge")

        if mode == "subscribe" and token == self.verify_token:
            return web.Response(text=challenge)
        return web.Response(text="Forbidden", status=403)

    async def _webhook_post(self, request):
        """Handle incoming WhatsApp messages."""
        try:
            data = await request.json()
        except Exception:
            return web.Response(text="Bad Request", status=400)

        if data.get("object") != "whatsapp_business_account":
            return web.Response(text="Not Found", status=404)

        for entry in data.get("entry", []):
            for change in entry.get("changes", []):
                messages = change.get("value", {}).get("messages", [])
                for msg in messages:
                    await self._handle_wa_message(msg, change.get("value", {}))

        return web.Response(text="OK")

    async def _handle_wa_message(self, msg: dict, metadata: dict):
        """Handle incoming WhatsApp message."""
        msg_type = msg.get("type")
        if msg_type != "text":
            return

        text = msg.get("text", {}).get("body", "")
        if not text:
            return

        from_id = msg.get("from")
        msg_id = msg.get("id")

        msg_obj = Message(
            text=text,
            user_id=from_id,
            chat_id=from_id,
            message_id=msg_id,
            raw=msg,
        )

        self.sessions[from_id] = {
            "chat_id": from_id,
            "user_id": from_id,
        }

        response = await self.handle_message(msg_obj)
        if response:
            await self.send_message(from_id, response)

    async def stop(self):
        """Stop the WhatsApp webhook server."""
        if self.runner:
            await self.runner.cleanup()
        logger.info("WhatsApp webhook server stopped")

    async def send_message(self, chat_id: str, text: str, thread_id: str = None) -> str:
        """Send a message to a WhatsApp chat."""
        if not self.access_token or not self.phone_number_id:
            logger.warning("WhatsApp access_token or phone_number_id not configured")
            return ""

        import httpx

        url = f"https://graph.facebook.com/v18.0/{self.phone_number_id}/messages"
        headers = {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json",
        }
        payload = {
            "messaging_product": "whatsapp",
            "to": chat_id,
            "type": "text",
            "text": {"body": text},
        }

        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(url, json=payload, headers=headers, timeout=30.0)
                data = response.json()
                return data.get("messages", [{}])[0].get("id", "")
        except Exception as e:
            logger.error(f"WhatsApp send error: {e}")
            return ""

    async def send_interactive_message(self, chat_id: str, text: str, buttons: list = None) -> str:
        """Send a message with interactive buttons to WhatsApp."""
        if not self.access_token or not self.phone_number_id:
            logger.warning("WhatsApp access_token or phone_number_id not configured")
            return ""

        if not buttons:
            return await self.send_message(chat_id, text)

        import httpx

        url = f"https://graph.facebook.com/v18.0/{self.phone_number_id}/messages"
        headers = {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json",
        }

        button_list = []
        for i, btn in enumerate(buttons):
            button_list.append(
                {
                    "type": "reply",
                    "reply": {
                        "id": btn.get("value", f"btn_{i}"),
                        "title": btn.get("text", "")[:25],  # WhatsApp limits button text
                    },
                }
            )

        payload = {
            "messaging_product": "whatsapp",
            "to": chat_id,
            "type": "interactive",
            "interactive": {
                "type": "button",
                "body": {"text": text},
                "action": {"buttons": button_list},
            },
        }

        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(url, json=payload, headers=headers, timeout=30.0)
                data = response.json()
                return data.get("messages", [{}])[0].get("id", "")
        except Exception as e:
            logger.error(f"WhatsApp interactive send error: {e}")
            return ""

    def verify_signature(self, payload: bytes, signature: str) -> bool:
        """Verify the webhook signature from Meta."""
        if not self.app_secret:
            return True

        expected = hmac.new(self.app_secret.encode(), payload, hashlib.sha256).hexdigest()

        return hmac.compare_digest(expected, signature)


def create_whatsapp_platform(config: dict = None) -> WhatsAppPlatform:
    """Factory function to create a WhatsApp platform."""
    return WhatsAppPlatform(config)
