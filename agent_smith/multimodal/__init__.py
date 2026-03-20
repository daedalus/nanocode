"""Multimodal support for the agent."""

import base64
import asyncio
from typing import Any, Optional
from dataclasses import dataclass


@dataclass
class ImageContent:
    """Image content for multimodal input."""

    url: Optional[str] = None
    base64: Optional[str] = None
    mime_type: str = "image/png"


class VisionProcessor:
    """Process images for vision-capable models."""

    def __init__(self, llm):
        self.llm = llm

    async def describe_image(self, image_path: str, prompt: str = None) -> str:
        """Get a description of an image."""
        with open(image_path, "rb") as f:
            image_data = base64.b64encode(f.read()).decode()

        prompt = prompt or "Describe this image in detail."

        from nanocode.llm import Message

        content = [
            {"type": "text", "text": prompt},
            {
                "type": "image_url",
                "image_url": {"url": f"data:image/png;base64,{image_data}"},
            },
        ]

        response = await self.llm.chat([Message("user", content)])
        return response.content

    def encode_image(self, image_path: str) -> str:
        """Encode an image to base64."""
        with open(image_path, "rb") as f:
            return base64.b64encode(f.read()).decode()

    def create_multimodal_message(self, text: str, images: list[str] = None) -> list[dict]:
        """Create a multimodal message content."""
        content = [{"type": "text", "text": text}]

        if images:
            for img_path in images:
                b64 = self.encode_image(img_path)
                content.append(
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/png;base64,{b64}"},
                    }
                )

        return content


class AudioProcessor:
    """Process audio for the agent."""

    def __init__(self):
        self.tts_available = False
        self.stt_available = False

    async def text_to_speech(self, text: str, output_path: str = None) -> bytes:
        """Convert text to speech."""
        raise NotImplementedError("TTS requires additional setup (e.g., edge-tts)")

    async def speech_to_text(self, audio_path: str) -> str:
        """Convert speech to text."""
        raise NotImplementedError("STT requires additional setup (e.g., whisper)")

    async def play_audio(self, audio_data: bytes):
        """Play audio data."""
        import io
        import subprocess

        try:
            process = subprocess.Popen(
                ["paplay", "--version"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            process.wait(timeout=5)

            cmd = ["paplay"]
            process = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            process.communicate(input=audio_data)
        except:
            pass


class DocumentProcessor:
    """Extract content from documents."""

    async def extract_text(self, file_path: str) -> str:
        """Extract text from a document."""
        import pathlib

        ext = pathlib.Path(file_path).suffix.lower()

        if ext == ".pdf":
            return await self._extract_pdf(file_path)
        elif ext in (".docx", ".doc"):
            return await self._extract_docx(file_path)
        elif ext in (".txt", ".md", ".py", ".js", ".json", ".yaml", ".yml"):
            with open(file_path) as f:
                return f.read()
        else:
            return "(Unsupported file format)"

    async def _extract_pdf(self, file_path: str) -> str:
        """Extract text from PDF."""
        try:
            import PyPDF2

            with open(file_path, "rb") as f:
                reader = PyPDF2.PdfReader(f)
                text = ""
                for page in reader.pages:
                    text += page.extract_text() + "\n"
                return text
        except ImportError:
            return "(PDF extraction requires PyPDF2: pip install PyPDF2)"
        except Exception as e:
            return f"(PDF extraction failed: {e})"

    async def _extract_docx(self, file_path: str) -> str:
        """Extract text from DOCX."""
        try:
            import docx

            doc = docx.Document(file_path)
            return "\n".join([p.text for p in doc.paragraphs])
        except ImportError:
            return "(DOCX extraction requires python-docx: pip install python-docx)"
        except Exception as e:
            return f"(DOCX extraction failed: {e})"


class MultimodalManager:
    """Manages all multimodal capabilities."""

    def __init__(self, llm=None):
        self.llm = llm
        self.vision = VisionProcessor(llm) if llm else None
        self.audio = AudioProcessor()
        self.document = DocumentProcessor()

    def supports_vision(self) -> bool:
        """Check if vision is available."""
        return self.vision is not None

    def supports_audio(self) -> bool:
        """Check if audio is available."""
        return self.audio.tts_available or self.audio.stt_available

    async def process_input(self, input_data: Any) -> str:
        """Process various input types."""
        import pathlib

        if isinstance(input_data, str):
            path = pathlib.Path(input_data)
            if path.exists() and path.is_file():
                if path.suffix.lower() in (".png", ".jpg", ".jpeg", ".gif", ".webp"):
                    if self.supports_vision():
                        return await self.vision.describe_image(input_data)
                    else:
                        return "(Vision not available)"
                else:
                    return await self.document.extract_text(input_data)
            return input_data

        return str(input_data)
