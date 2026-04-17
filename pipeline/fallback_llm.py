"""Fallback LLM service: Mistral primary, Groq secondary.

Tries Mistral first (strong tool-use). On a rate-limit error, falls back to
Groq's Llama for a cooldown window, then retries Mistral. Groq's OpenAI-
compatible endpoint is called directly via the openai client so we don't
drag in a second Pipecat LLM stack.
"""

import time

from loguru import logger
from openai import AsyncOpenAI, RateLimitError

from pipecat.adapters.services.open_ai_adapter import OpenAILLMInvocationParams
from pipecat.services.llm_service import FunctionCallRunnerItem
from pipecat.services.mistral.llm import MistralLLMService


class FallbackLLMService(MistralLLMService):
    """Mistral LLM with automatic fallback to Groq on rate limit."""

    def __init__(
        self,
        *,
        api_key: str,
        groq_api_key: str,
        groq_model: str = "llama-3.3-70b-versatile",
        groq_base_url: str = "https://api.groq.com/openai/v1",
        fallback_cooldown: float = 60.0,
        **kwargs,
    ):
        """Initialize the fallback LLM service.

        Args:
            api_key: Mistral API key (primary).
            groq_api_key: Groq API key (fallback).
            groq_model: Model to use on Groq.
            groq_base_url: Groq's OpenAI-compatible base URL.
            fallback_cooldown: Seconds to stay on fallback before retrying Mistral.
            **kwargs: Additional args passed to MistralLLMService.
        """
        super().__init__(api_key=api_key, **kwargs)

        self._groq_client = AsyncOpenAI(
            api_key=groq_api_key,
            base_url=groq_base_url,
        )
        self._groq_model = groq_model
        self._fallback_cooldown = fallback_cooldown
        self._using_fallback = False
        self._fallback_until = 0.0

    async def _run_function_call(self, runner_item: FunctionCallRunnerItem):
        # Pipecat's stream parser yields None when the LLM calls a no-arg tool.
        # DirectFunctionWrapper.invoke then does `**None` and crashes. Normalize
        # to an empty dict so the downstream **args unpack works.
        if runner_item.arguments is None:
            runner_item.arguments = {}
        return await super()._run_function_call(runner_item)

    async def get_chat_completions(self, params_from_context: OpenAILLMInvocationParams):
        """Try Mistral first, fall back to Groq on rate limits."""
        # In fallback cooldown → go straight to Groq
        if self._using_fallback and time.monotonic() < self._fallback_until:
            return await self._groq_completions(params_from_context)

        if self._using_fallback:
            self._using_fallback = False
            logger.info("Fallback cooldown expired, switching back to Mistral")

        try:
            return await super().get_chat_completions(params_from_context)
        except RateLimitError as e:
            logger.warning(f"Mistral rate limited: {e}. Falling back to Groq")
            self._using_fallback = True
            self._fallback_until = time.monotonic() + self._fallback_cooldown
            return await self._groq_completions(params_from_context)

    async def _groq_completions(self, params_from_context: OpenAILLMInvocationParams):
        """Make a chat completion request against Groq."""
        params = self.build_chat_completion_params(params_from_context)
        params["model"] = self._groq_model

        logger.debug(f"{self}: Using Groq fallback ({self._groq_model})")
        return await self._groq_client.chat.completions.create(**params)
