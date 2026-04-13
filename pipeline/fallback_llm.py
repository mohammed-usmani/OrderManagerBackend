"""Fallback LLM service: Groq primary, NVIDIA NIM secondary.

If Groq returns a rate limit error (429), automatically retries the
same request against NVIDIA NIM's OpenAI-compatible API.
"""

import time

from loguru import logger
from openai import AsyncOpenAI, RateLimitError

from pipecat.adapters.services.open_ai_adapter import OpenAILLMInvocationParams
from pipecat.services.groq.llm import GroqLLMService


class FallbackLLMService(GroqLLMService):
    """Groq LLM with automatic fallback to NVIDIA NIM on rate limit."""

    def __init__(
        self,
        *,
        api_key: str,
        nvidia_api_key: str,
        nvidia_model: str = "meta/llama-3.3-70b-instruct",
        nvidia_base_url: str = "https://integrate.api.nvidia.com/v1",
        fallback_cooldown: float = 60.0,
        **kwargs,
    ):
        """Initialize the fallback LLM service.

        Args:
            api_key: Groq API key (primary).
            nvidia_api_key: NVIDIA NIM API key (fallback).
            nvidia_model: Model to use on NVIDIA NIM.
            nvidia_base_url: NVIDIA NIM API base URL.
            fallback_cooldown: Seconds to stay on fallback before retrying Groq.
            **kwargs: Additional args passed to GroqLLMService.
        """
        super().__init__(api_key=api_key, **kwargs)

        self._nvidia_client = AsyncOpenAI(
            api_key=nvidia_api_key,
            base_url=nvidia_base_url,
        )
        self._nvidia_model = nvidia_model
        self._fallback_cooldown = fallback_cooldown
        self._using_fallback = False
        self._fallback_until = 0.0

    async def get_chat_completions(self, params_from_context: OpenAILLMInvocationParams):
        """Get chat completions with automatic Groq -> NVIDIA NIM fallback.

        If currently in fallback cooldown, goes directly to NVIDIA NIM.
        Otherwise tries Groq first, falls back on RateLimitError.
        """
        # If we're in fallback cooldown, go straight to NVIDIA NIM
        if self._using_fallback and time.monotonic() < self._fallback_until:
            return await self._nvidia_completions(params_from_context)

        # Cooldown expired, try Groq again
        if self._using_fallback:
            self._using_fallback = False
            logger.info("Fallback cooldown expired, switching back to Groq")

        try:
            return await super().get_chat_completions(params_from_context)
        except RateLimitError as e:
            logger.warning(f"Groq rate limited: {e}. Falling back to NVIDIA NIM")
            self._using_fallback = True
            self._fallback_until = time.monotonic() + self._fallback_cooldown
            return await self._nvidia_completions(params_from_context)

    async def _nvidia_completions(self, params_from_context: OpenAILLMInvocationParams):
        """Make a chat completion request against NVIDIA NIM."""
        params = self.build_chat_completion_params(params_from_context)
        # Override model for NVIDIA
        params["model"] = self._nvidia_model

        logger.debug(f"{self}: Using NVIDIA NIM fallback ({self._nvidia_model})")
        chunks = await self._nvidia_client.chat.completions.create(**params)
        return chunks
