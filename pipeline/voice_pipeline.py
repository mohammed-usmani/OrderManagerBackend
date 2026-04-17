"""Voice pipeline factory: creates a Pipecat pipeline per WebSocket connection.

For voice chat only. Text chat goes through the REST /chat endpoint
and the LangGraph agent directly.
"""

from fastapi import WebSocket

from pipecat.adapters.schemas.direct_function import DirectFunctionWrapper
from pipecat.adapters.schemas.tools_schema import ToolsSchema
from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.pipeline.pipeline import Pipeline
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.aggregators.llm_response_universal import (
    LLMContextAggregatorPair,
    LLMUserAggregatorParams,
)
from pipecat.serializers.protobuf import ProtobufFrameSerializer
from pipecat.services.llm_service import FunctionCallParams
from pipecat.transports.websocket.fastapi import (
    FastAPIWebsocketParams,
    FastAPIWebsocketTransport,
)

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
from config import GROQ_API_KEY, MISTRAL_API_KEY, NVIDIA_API_KEY, VOICE_ID
from pipeline.fallback_llm import FallbackLLMService
from pipeline.voxtral_stt import VoxtralSTTService
from pipeline.voxtral_tts import VoxtralTTSService


def _make_tool_wrappers(user_id: str, user_timezone: str | None = None):
    """Create Pipecat tool wrappers that inject user_id + timezone via RunnableConfig."""

    config = {"configurable": {"user_id": user_id, "user_timezone": user_timezone}}

    # Loop guard: some LLMs (NVIDIA Llama 3.3) get stuck calling the same tool
    # over and over instead of replying. Track the last N calls per tool and
    # short-circuit when we detect a repeat.
    MAX_REPEATS = 2
    recent_calls: dict[str, list[str]] = {}

    def _loop_guard(name: str, args_signature: str) -> str | None:
        history = recent_calls.setdefault(name, [])
        history.append(args_signature)
        if len(history) > MAX_REPEATS + 1:
            history.pop(0)
        if len(history) > MAX_REPEATS and all(a == args_signature for a in history):
            # Reset so a user turn can start fresh afterwards
            recent_calls[name] = []
            return (
                f"STOP LOOPING. You have already called {name} with these "
                f"arguments {MAX_REPEATS + 1} times in a row. The results you "
                "already have are the complete and correct answer. Respond to "
                "the user with a plain-text message now — do NOT call any more "
                "tools until the user speaks again."
            )
        return None

    async def pc_search_menu(params: FunctionCallParams, query: str) -> None:
        """Search the restaurant menu by dish name or item ID.

        Args:
            query: The dish name or ID to search for.
        """
        stop = _loop_guard("pc_search_menu", f"query={query}")
        if stop:
            await params.result_callback(stop)
            return
        await params.result_callback(search_menu.invoke({"query": query}, config=config))

    async def pc_get_menu_categories(params: FunctionCallParams) -> None:
        """Get an overview of all menu categories and their items with prices."""
        stop = _loop_guard("pc_get_menu_categories", "")
        if stop:
            await params.result_callback(stop)
            return
        await params.result_callback(get_menu_categories.invoke({}, config=config))

    async def pc_add_to_order(
        params: FunctionCallParams,
        item_id: str,
        quantity: int = 1,
        special_instructions: str = "",
    ) -> None:
        """Add an item to the customer's order.

        Args:
            item_id: The menu item ID (e.g. 'M01', 'S02').
            quantity: Number of this item to add.
            special_instructions: Any special requests.
        """
        sig = f"item_id={item_id}|qty={quantity}|instr={special_instructions}"
        stop = _loop_guard("pc_add_to_order", sig)
        if stop:
            await params.result_callback(stop)
            return
        await params.result_callback(
            add_to_order.invoke({
                "item_id": item_id,
                "quantity": quantity,
                "special_instructions": special_instructions,
            }, config=config)
        )

    async def pc_view_order(params: FunctionCallParams) -> None:
        """View the customer's current in-progress cart (items not yet confirmed).

        For past/historical orders, use search_my_orders instead.
        """
        stop = _loop_guard("pc_view_order", "")
        if stop:
            await params.result_callback(stop)
            return
        await params.result_callback(view_order.invoke({}, config=config))

    async def pc_search_my_orders(
        params: FunctionCallParams,
        status: str = "",
        limit: int = 5,
    ) -> None:
        """Search the customer's past orders, optionally filtered by status.

        Use when the customer asks about order history or counts by status.

        Args:
            status: Optional status filter: "cart", "confirmed",
                "awaiting_payment", "paid", or "cancelled". Empty returns a
                summary across all statuses.
            limit: Max orders to return detail rows for (default 5).
        """
        stop = _loop_guard("pc_search_my_orders", f"status={status}|limit={limit}")
        if stop:
            await params.result_callback(stop)
            return
        await params.result_callback(
            search_my_orders.invoke(
                {"status": status, "limit": limit}, config=config
            )
        )

    async def pc_remove_from_order(params: FunctionCallParams, item_id: str) -> None:
        """Remove an item from the order by menu item ID.

        Args:
            item_id: The menu item ID to remove (e.g. 'M01').
        """
        stop = _loop_guard("pc_remove_from_order", f"item_id={item_id}")
        if stop:
            await params.result_callback(stop)
            return
        await params.result_callback(remove_from_order.invoke({"item_id": item_id}, config=config))

    async def pc_confirm_order(params: FunctionCallParams) -> None:
        """Confirm and send the customer's order to the kitchen."""
        stop = _loop_guard("pc_confirm_order", "")
        if stop:
            await params.result_callback(stop)
            return
        await params.result_callback(confirm_order.invoke({}, config=config))

    async def pc_cancel_order(params: FunctionCallParams) -> None:
        """Cancel the customer's current order."""
        stop = _loop_guard("pc_cancel_order", "")
        if stop:
            await params.result_callback(stop)
            return
        await params.result_callback(cancel_order.invoke({}, config=config))

    async def pc_get_current_datetime(params: FunctionCallParams) -> None:
        """Get the current date, time, and day of week."""
        stop = _loop_guard("pc_get_current_datetime", "")
        if stop:
            await params.result_callback(stop)
            return
        await params.result_callback(get_current_datetime.invoke({}))

    async def pc_save_note(params: FunctionCallParams, content: str, category: str = "general") -> None:
        """Save a note with a category.

        Args:
            content: The content of the note to save.
            category: The category for the note.
        """
        stop = _loop_guard("pc_save_note", f"content={content[:50]}|category={category}")
        if stop:
            await params.result_callback(stop)
            return
        await params.result_callback(save_note.invoke({"content": content, "category": category}))

    async def pc_list_notes(params: FunctionCallParams, category: str | None = None) -> None:
        """List saved notes, optionally filtered by category.

        Args:
            category: Optional category to filter notes by.
        """
        stop = _loop_guard("pc_list_notes", f"category={category}")
        if stop:
            await params.result_callback(stop)
            return
        await params.result_callback(list_notes.invoke({"category": category}))

    async def pc_delete_note(params: FunctionCallParams, note_id: str) -> None:
        """Delete a note by its ID.

        Args:
            note_id: The ID of the note to delete.
        """
        stop = _loop_guard("pc_delete_note", f"note_id={note_id}")
        if stop:
            await params.result_callback(stop)
            return
        await params.result_callback(delete_note.invoke({"note_id": note_id}))

    return [
        pc_search_menu,
        pc_get_menu_categories,
        pc_add_to_order,
        pc_view_order,
        pc_search_my_orders,
        pc_remove_from_order,
        pc_confirm_order,
        pc_cancel_order,
        pc_get_current_datetime,
        pc_save_note,
        pc_list_notes,
        pc_delete_note,
    ]


# --- Pipeline factory ---


def create_pipeline(
    websocket: WebSocket,
    user_id: str = None,
    user_timezone: str | None = None,
):
    """Create a fresh voice pipeline for a single client connection."""
    transport = FastAPIWebsocketTransport(
        websocket=websocket,
        params=FastAPIWebsocketParams(
            audio_in_enabled=True,
            audio_out_enabled=True,
            serializer=ProtobufFrameSerializer(),
        ),
    )

    stt = VoxtralSTTService(api_key=MISTRAL_API_KEY)

    # Prepend fresh time context to the system prompt so the LLM has the real
    # current time in both the restaurant's timezone and the customer's.
    system_instruction = (
        build_time_context_message(user_timezone) + "\n\n" + SYSTEM_PROMPT
    )

    llm = FallbackLLMService(
        api_key=MISTRAL_API_KEY,
        groq_api_key=GROQ_API_KEY,
        groq_model="llama-3.3-70b-versatile",
        settings=FallbackLLMService.Settings(
            model="mistral-large-latest",
            system_instruction=system_instruction,
        ),
    )

    # Register tools with user_id + timezone baked in, collect schemas for context.
    tool_fns = _make_tool_wrappers(user_id or "", user_timezone)
    tool_schemas = []
    for tool_fn in tool_fns:
        llm.register_direct_function(tool_fn)
        wrapper = DirectFunctionWrapper(tool_fn)
        tool_schemas.append(wrapper.to_function_schema())

    tts = VoxtralTTSService(api_key=MISTRAL_API_KEY, voice_id=VOICE_ID)

    context = LLMContext()
    context.set_tools(ToolsSchema(standard_tools=tool_schemas))
    context_pair = LLMContextAggregatorPair(
        context,
        user_params=LLMUserAggregatorParams(
            vad_analyzer=SileroVADAnalyzer(),
        ),
    )

    pipeline = Pipeline(
        [
            transport.input(),
            stt,
            context_pair.user(),
            llm,
            tts,
            transport.output(),
            context_pair.assistant(),
        ]
    )

    return pipeline
