"""Token counting utilities using tiktoken with cl100k_base encoding."""

import os
from functools import lru_cache

import tiktoken

# Support pre-downloaded cache dir if set
TIKTOKEN_CACHE_DIR = os.getenv("TIKTOKEN_CACHE_DIR")


@lru_cache(maxsize=1)
def get_cl100k_encoding() -> tiktoken.Encoding:
    """Return the cached cl100k_base tokenizer."""
    return tiktoken.get_encoding("cl100k_base")


def count_tokens(text: str) -> int:
    """Count tokens in text using cl100k_base encoding.

    Args:
        text: String to tokenize.

    Returns:
        Number of tokens.
    """
    if not text:
        return 0
    enc = get_cl100k_encoding()
    return len(enc.encode(text, disallowed_special=()))
