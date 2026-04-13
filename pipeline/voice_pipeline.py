"""Voice pipeline factory: creates a Pipecat pipeline per WebSocket connection.

For voice chat only. Text chat goes through the REST /chat endpoint
and the LangGraph agent directly.
"""

from fastapi import WebSocket

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
from config import GROQ_API_KEY, MISTRAL_API_KEY, NVIDIA_API_KEY, VOICE_ID
from pipeline.fallback_llm import FallbackLLMService
from pipeline.voxtral_stt import VoxtralSTTService
from pipeline.voxtral_tts import VoxtralTTSService


# --- Pipecat tool wrappers ---
# These wrap the LangChain @tool functions so they work with Pipecat's
# direct function calling. Each calls the LangChain tool's .invoke() method.


async def _pc_search_menu(params: FunctionCallParams, query: str) -> None:
    """Search the restaurant menu by dish name or item ID.

    Args:
        query: The dish name or ID to search for.
    """
    await params.result_callback(search_menu.invoke({"query": query}))


async def _pc_get_menu_categories(params: FunctionCallParams) -> None:
    """Get an overview of all menu categories and their items with prices."""
    await params.result_callback(get_menu_categories.invoke({}))


async def _pc_add_to_order(
    params: FunctionCallParams,
    table_id: str,
    item_id: str,
    quantity: int = 1,
    special_instructions: str = "",
) -> None:
    """Add an item to a table's order.

    Args:
        table_id: The table number or customer name.
        item_id: The menu item ID (e.g. 'M01', 'S02').
        quantity: Number of this item to add.
        special_instructions: Any special requests.
    """
    await params.result_callback(
        add_to_order.invoke({
            "table_id": table_id,
            "item_id": item_id,
            "quantity": quantity,
            "special_instructions": special_instructions,
        })
    )


async def _pc_view_order(params: FunctionCallParams, table_id: str) -> None:
    """View the current order for a table.

    Args:
        table_id: The table number or customer name.
    """
    await params.result_callback(view_order.invoke({"table_id": table_id}))


async def _pc_remove_from_order(params: FunctionCallParams, table_id: str, item_name: str) -> None:
    """Remove an item from a table's order by dish name.

    Args:
        table_id: The table number or customer name.
        item_name: The name of the dish to remove.
    """
    await params.result_callback(remove_from_order.invoke({"table_id": table_id, "item_name": item_name}))


async def _pc_confirm_order(params: FunctionCallParams, table_id: str) -> None:
    """Confirm and send a table's order to the kitchen.

    Args:
        table_id: The table number or customer name.
    """
    await params.result_callback(confirm_order.invoke({"table_id": table_id}))


async def _pc_cancel_order(params: FunctionCallParams, table_id: str) -> None:
    """Cancel a table's entire order.

    Args:
        table_id: The table number or customer name.
    """
    await params.result_callback(cancel_order.invoke({"table_id": table_id}))


async def _pc_get_current_datetime(params: FunctionCallParams) -> None:
    """Get the current date, time, and day of week."""
    await params.result_callback(get_current_datetime.invoke({}))


async def _pc_save_note(params: FunctionCallParams, content: str, category: str = "general") -> None:
    """Save a note with a category.

    Args:
        content: The content of the note to save.
        category: The category for the note.
    """
    await params.result_callback(save_note.invoke({"content": content, "category": category}))


async def _pc_list_notes(params: FunctionCallParams, category: str | None = None) -> None:
    """List saved notes, optionally filtered by category.

    Args:
        category: Optional category to filter notes by.
    """
    await params.result_callback(list_notes.invoke({"category": category}))


async def _pc_delete_note(params: FunctionCallParams, note_id: str) -> None:
    """Delete a note by its ID.

    Args:
        note_id: The ID of the note to delete.
    """
    await params.result_callback(delete_note.invoke({"note_id": note_id}))


# --- Pipeline factory ---


def create_pipeline(websocket: WebSocket, user_id: str = None):
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

    llm = FallbackLLMService(
        api_key=GROQ_API_KEY,
        nvidia_api_key=NVIDIA_API_KEY,
        nvidia_model="meta/llama-3.3-70b-instruct",
        settings=FallbackLLMService.Settings(
            model="llama-3.3-70b-versatile",
            system_instruction=SYSTEM_PROMPT,
        ),
    )

    # Register all tools
    llm.register_direct_function(_pc_search_menu)
    llm.register_direct_function(_pc_get_menu_categories)
    llm.register_direct_function(_pc_add_to_order)
    llm.register_direct_function(_pc_view_order)
    llm.register_direct_function(_pc_remove_from_order)
    llm.register_direct_function(_pc_confirm_order)
    llm.register_direct_function(_pc_cancel_order)
    llm.register_direct_function(_pc_get_current_datetime)
    llm.register_direct_function(_pc_save_note)
    llm.register_direct_function(_pc_list_notes)
    llm.register_direct_function(_pc_delete_note)

    tts = VoxtralTTSService(api_key=MISTRAL_API_KEY, voice_id=VOICE_ID)

    context = LLMContext()
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
