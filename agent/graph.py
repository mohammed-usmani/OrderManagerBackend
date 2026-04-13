"""LangGraph agent: the shared brain for both text and voice interfaces.

Uses Groq as primary LLM with NVIDIA NIM as fallback on rate limits.
"""

from langchain_core.messages import HumanMessage
from langchain_groq import ChatGroq
from langchain_nvidia_ai_endpoints import ChatNVIDIA
from langgraph.prebuilt import create_react_agent

from agent.brain import SYSTEM_PROMPT
from agent.tools.datetime_tools import get_current_datetime
from agent.tools.notes import delete_note, list_notes, save_note
from agent.tools.orders import (
    add_to_order,
    cancel_order,
    confirm_order,
    get_menu_categories,
    remove_from_order,
    search_menu,
    view_order,
)
from config import GROQ_API_KEY, NVIDIA_API_KEY

ALL_TOOLS = [
    # Menu & ordering
    search_menu,
    get_menu_categories,
    add_to_order,
    view_order,
    remove_from_order,
    confirm_order,
    cancel_order,
    # Utilities
    get_current_datetime,
    save_note,
    list_notes,
    delete_note,
]


def _create_groq_llm():
    return ChatGroq(
        api_key=GROQ_API_KEY,
        model="llama-3.3-70b-versatile",
        temperature=0.7,
    )


def _create_nvidia_llm():
    return ChatNVIDIA(
        api_key=NVIDIA_API_KEY,
        model="meta/llama-3.3-70b-instruct",
        temperature=0.7,
    )


def create_agent():
    """Create the primary LangGraph ReAct agent (Groq-backed)."""
    return create_react_agent(
        model=_create_groq_llm(),
        tools=ALL_TOOLS,
        prompt=SYSTEM_PROMPT,
    )


def create_fallback_agent():
    """Create the fallback LangGraph ReAct agent (NVIDIA NIM-backed)."""
    return create_react_agent(
        model=_create_nvidia_llm(),
        tools=ALL_TOOLS,
        prompt=SYSTEM_PROMPT,
    )


async def invoke_agent(
    agent,
    fallback_agent,
    message: str,
    thread_id: str,
) -> str:
    """Invoke the agent with a message, falling back on rate limits.

    Args:
        agent: Primary LangGraph agent (Groq).
        fallback_agent: Fallback LangGraph agent (NVIDIA NIM).
        message: User message text.
        thread_id: Conversation thread ID for state persistence.

    Returns:
        The assistant's text response.
    """
    config = {"configurable": {"thread_id": thread_id}}
    inputs = {"messages": [HumanMessage(content=message)]}

    try:
        result = await agent.ainvoke(inputs, config=config)
        return result["messages"][-1].content
    except Exception as e:
        error_str = str(e).lower()
        if "rate" in error_str or "429" in error_str or "limit" in error_str:
            from loguru import logger

            logger.warning(f"Groq rate limited, falling back to NVIDIA NIM: {e}")
            result = await fallback_agent.ainvoke(inputs, config=config)
            return result["messages"][-1].content
        raise
