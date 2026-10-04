"""Agent turn + tool spans."""

import json

from langchain_core.messages import AIMessage

from tests.conftest import span_rows


async def test_run_agent_span_wraps_tool_spans(traced, session_db, monkeypatch):
    from app.agent import graph, toolkit

    class FakeAgent:
        async def ainvoke(self, state, config):
            await toolkit.get_current_time.ainvoke({})
            return {"messages": [AIMessage(content="It is noon.")]}

    async def fake_get_agent():
        return FakeAgent()

    monkeypatch.setattr(graph, "get_agent", fake_get_agent)
    reply = await graph.run_agent("what time is it?", thread_id="42")
    assert reply == "It is noon."

    (agent,) = span_rows(operation="invoke_agent")
    (tool,) = span_rows(operation="execute_tool")
    assert agent.name == "invoke_agent rotom"
    assert tool.name == "execute_tool get_current_time"
    assert tool.parent_span_id == agent.span_id
    attrs = json.loads(agent.attributes)
    assert attrs["gen_ai.conversation.id"] == "42"
    assert json.loads(attrs["gen_ai.output.messages"])[0]["content"] == "It is noon."
    assert "timezone" in json.loads(tool.attributes)["gen_ai.tool.call.result"]


def test_sync_tool_span_captures_args_and_result(traced, session_db):
    from app.agent import toolkit

    toolkit.list_emails.invoke({"category": "critical", "limit": 3})
    (tool,) = span_rows(operation="execute_tool")
    attrs = json.loads(tool.attributes)
    assert attrs["gen_ai.tool.name"] == "list_emails"
    assert json.loads(attrs["gen_ai.tool.call.arguments"]) == {"category": "critical", "limit": 3}


def test_tool_error_marks_span_error(traced):
    import pytest
    from langchain_core.tools import tool

    from app.agent.toolkit import traced_tool

    @tool
    def explode(x: int) -> str:
        """Always fails."""
        raise RuntimeError("kaboom")

    t = traced_tool(explode)
    with pytest.raises(RuntimeError):
        t.invoke({"x": 1})
    (row,) = span_rows(operation="execute_tool")
    assert row.status == "ERROR"


def test_all_tools_are_traced_and_keep_schemas():
    from app.agent.toolkit import ALL_TOOLS

    for t in ALL_TOOLS:
        fn = t.coroutine or t.func
        assert getattr(fn, "__rotom_traced__", False), t.name
    names = {t.name for t in ALL_TOOLS}
    assert {"list_emails", "create_reminder", "run_gmail_triage"} <= names
