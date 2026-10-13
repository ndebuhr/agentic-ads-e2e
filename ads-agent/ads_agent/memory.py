"""Long-term memory: facts the user wants kept across sessions.

Memories are written only through `remember`, one explicit fact at a time,
rather than by indexing whole sessions, so account data and tool output stay
out of memory. `preload_memory` adds the memories that match each request to
the model's context. Where they are stored is set by the web server's
--memory_service_uri (SQLite locally, Vertex AI Memory Bank when deployed);
without it they last until the server stops.
"""
from google.adk.events import Event
from google.adk.tools import ToolContext
from google.genai import types


async def remember(fact: str, tool_context: ToolContext) -> dict:
    """Saves a fact for future sessions.

    Use it only for something the user states or approves that will matter
    again: brand facts and voice, approved landing page URLs, standing rules,
    and decisions with their reasons, such as a keyword that was dropped
    because the page doesn't back it up. Never save credentials, account
    performance data, or anything the user asks you not to keep.

    Args:
      fact: One self-contained statement, for example "Ad final URLs use the
        product page, never the store home page."
    """
    event = Event(author="user", content=types.Content(role="user", parts=[types.Part(text=fact)]))
    try:
        await tool_context.add_events_to_memory(events=[event])
    except (ValueError, NotImplementedError) as e:
        return {"error": f"Memory is not available: {e}"}
    return {"remembered": fact}
