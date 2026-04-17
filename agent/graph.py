"""LangGraph agent: the shared brain for both text and voice interfaces.

Uses Mistral as primary LLM with Groq as fallback on rate limits / malformed
tool calls.
"""

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_groq import ChatGroq
from langchain_mistralai import ChatMistralAI
from langgraph.prebuilt import create_react_agent

from agent.brain import SYSTEM_PROMPT, build_time_context_message
from agent.tools.datetime_tools import get_current_datetime
from agent.tools.notes import delete_note, list_notes, save_note
from agent.tools.orders import (
    add_to_order,
    cancel_order,
    confirm_order,
    get_menu_categories,
    remove_from_order,
    search_menu,
    search_my_orders,
    view_order,
)
from config import GROQ_API_KEY, MISTRAL_API_KEY

ALL_TOOLS = [
    # Menu & ordering
    search_menu,
    get_menu_categories,
    add_to_order,
    view_order,
    search_my_orders,
    remove_from_order,
    confirm_order,
    cancel_order,
    # Utilities
    get_current_datetime,
    save_note,
    list_notes,
    delete_note,
]


def _create_mistral_llm():
    return ChatMistralAI(
        api_key=MISTRAL_API_KEY,
        model="mistral-large-latest",
        temperature=0.7,
    )


def _create_groq_llm():
    return ChatGroq(
        api_key=GROQ_API_KEY,
        model="llama-3.3-70b-versatile",
        temperature=0.7,
    )


def create_agent():
    """Create the primary LangGraph ReAct agent (Mistral-backed)."""
    return create_react_agent(
        model=_create_mistral_llm(),
        tools=ALL_TOOLS,
        prompt=SYSTEM_PROMPT,
    )


def create_fallback_agent():
    """Create the fallback LangGraph ReAct agent (Groq-backed)."""
    return create_react_agent(
        model=_create_groq_llm(),
        tools=ALL_TOOLS,
        prompt=SYSTEM_PROMPT,
    )


async def invoke_agent(
    agent,
    fallback_agent,
    message: str,
    thread_id: str,
    user_id: str = None,
    prior_messages: list = None,
    user_timezone: str = None,
) -> str:
    """Invoke the agent with a message, falling back on rate limits.

    Args:
        agent: Primary LangGraph agent (Groq).
        fallback_agent: Fallback LangGraph agent (NVIDIA NIM).
        message: User message text.
        thread_id: Conversation thread ID for state persistence.
        user_id: Optional user ID for configurable context.
        prior_messages: Optional list of prior LangChain messages to prepend.

    Returns:
        The assistant's text response.
    """
    config = {
        "configurable": {
            "thread_id": thread_id,
            "user_id": user_id,
            "user_timezone": user_timezone,
        }
    }

    history = prior_messages or []
    # Fresh time context every turn (the static SYSTEM_PROMPT's time is stale).
    time_msg = SystemMessage(content=build_time_context_message(user_timezone))
    inputs = {"messages": [time_msg] + history + [HumanMessage(content=message)]}

    from loguru import logger

    def _should_fallback(err: Exception) -> bool:
        msg = str(err).lower()
        # Rate limit
        if "rate" in msg or "429" in msg or "limit" in msg:
            return True
        # Groq's Llama sometimes emits malformed tool calls like
        # `<function=search_menu {...}>`. Groq server rejects with
        # "tool_use_failed" / "tool call validation failed". Retry on NVIDIA.
        if "tool_use_failed" in msg or "tool call validation failed" in msg:
            return True
        return False

    try:
        result = await agent.ainvoke(inputs, config=config)
        return result["messages"][-1].content
    except Exception as e:
        if _should_fallback(e):
            logger.warning(
                f"Mistral failed ({e.__class__.__name__}), falling back to Groq: {e}"
            )
            result = await fallback_agent.ainvoke(inputs, config=config)
            return result["messages"][-1].content
        raise
