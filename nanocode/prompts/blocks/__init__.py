"""Composable negative-prompting blocks.

Each module exports a ``BLOCK`` constant (str) that can be composed into the
system prompt in ``core.py``.
"""

from nanocode.prompts.blocks.code_taste import BLOCK as CODE_TASTE_BLOCK
from nanocode.prompts.blocks.architecture import BLOCK as ARCHITECTURE_BLOCK
from nanocode.prompts.blocks.quality import BLOCK as QUALITY_BLOCK

__all__ = ["CODE_TASTE_BLOCK", "ARCHITECTURE_BLOCK", "QUALITY_BLOCK"]


def compose_negative_blocks() -> str:
    """Concatenate all available negative-prompting blocks."""
    return "\n\n".join([CODE_TASTE_BLOCK, ARCHITECTURE_BLOCK, QUALITY_BLOCK])
