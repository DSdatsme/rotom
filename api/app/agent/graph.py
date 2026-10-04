"""LangGraph chat agent: tool-calling loop with persistent SQLite checkpointing.

Thread id = Telegram chat id, so conversation context survives process restarts.
"""

import logging

from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.prebuilt import create_react_agent

from app.agent.prompts import SYSTEM_PROMPT
from app.agent.toolkit import ALL_TOOLS
from app.config import get_settings
from app.llm.provider import get_chat_model

logger = logging.getLogger(__name__)

_agent = None
_saver_cm = None


async def get_agent():
    """Lazily build the agent once per process."""
    global _agent, _saver_cm
    if _agent is None:
        settings = get_settings()
        _saver_cm = AsyncSqliteSaver.from_conn_string(settings.checkpoint_db_path)
        checkpointer = await _saver_cm.__aenter__()
        _agent = create_react_agent(
            get_chat_model("chat", settings),
            tools=ALL_TOOLS,
            prompt=SYSTEM_PROMPT,
            checkpointer=checkpointer,
        )
    return _agent


async def run_agent(message: str, thread_id: str) -> str:
    """Send one user message through the agent; return its final text reply.

    The whole turn is one `invoke_agent rotom` span; the agent's LLM calls and tool
    spans nest under it."""
    from app.llm.provider import extract_text
    from app.observability import semconv as sc
    from app.observability.tracing import get_tracer, set_content

    agent = await get_agent()
    with get_tracer().start_as_current_span(
        "invoke_agent rotom",
        attributes={sc.OPERATION_NAME: sc.OP_INVOKE_AGENT, sc.AGENT_NAME: "rotom",
                    sc.CONVERSATION_ID: thread_id},
    ) as turn:
        set_content(turn, sc.INPUT_MESSAGES, [{"role": "user", "content": message}])
        state = await agent.ainvoke(
            {"messages": [{"role": "user", "content": message}]},
            config={"configurable": {"thread_id": thread_id}, "recursion_limit": 25},
        )
        reply = extract_text(state["messages"][-1].content) or "(no reply)"
        set_content(turn, sc.OUTPUT_MESSAGES, [{"role": "assistant", "content": reply}])
        return reply


async def close_agent() -> None:
    global _agent, _saver_cm
    if _saver_cm is not None:
        await _saver_cm.__aexit__(None, None, None)
    _agent = None
    _saver_cm = None
