"""LlmTracingCallback: one `chat {model}` CLIENT span per LLM call (OTel GenAI semconv).

The span's parent is whatever span is current when the call starts — LangChain copies
contextvars into its callback hops, so calls made inside a run/step/tool nest under it.
In-flight spans are keyed by LangChain's per-call run id and always ended, on success
(`on_llm_end`) or failure (`on_llm_error`).
"""

import logging
import threading
from typing import Any

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.outputs import LLMResult
from opentelemetry.trace import SpanKind, Status, StatusCode

from app.observability import semconv as sc
from app.observability.pricing import cost_usd
from app.observability.tracing import get_tracer, set_content

logger = logging.getLogger(__name__)

_ROLES = {"human": "user", "ai": "assistant", "system": "system", "tool": "tool"}


def _text(content: Any) -> str:
    from app.llm.provider import extract_text  # lazy: provider imports this module

    return extract_text(content)


def _message(m: Any) -> dict[str, Any]:
    out: dict[str, Any] = {"role": _ROLES.get(getattr(m, "type", ""), getattr(m, "type", "unknown")),
                           "content": _text(getattr(m, "content", ""))}
    calls = getattr(m, "tool_calls", None)
    if calls:
        out["tool_calls"] = [{"name": c.get("name"), "args": c.get("args")} for c in calls]
    return out


def _usage(response: LLMResult) -> dict[str, Any]:
    u: dict[str, Any] = {"input": 0, "output": 0, "cache_read": 0, "reasoning": 0,
                         "model": None, "finish": [], "messages": []}
    llm_output = response.llm_output or {}
    token_usage = llm_output.get("token_usage") or {}
    u["input"] = token_usage.get("prompt_tokens", 0) or 0
    u["output"] = token_usage.get("completion_tokens", 0) or 0
    u["model"] = llm_output.get("model_name") or llm_output.get("model")
    for generations in response.generations:
        for g in generations:
            message = getattr(g, "message", None)
            finish = (g.generation_info or {}).get("finish_reason")
            if message is not None:
                um = getattr(message, "usage_metadata", None)
                if um:
                    u["input"] = um.get("input_tokens", u["input"]) or 0
                    u["output"] = um.get("output_tokens", u["output"]) or 0
                    u["cache_read"] = (um.get("input_token_details") or {}).get("cache_read", 0) or 0
                    u["reasoning"] = (um.get("output_token_details") or {}).get("reasoning", 0) or 0
                rm = getattr(message, "response_metadata", None) or {}
                u["model"] = rm.get("model_name") or rm.get("model") or u["model"]
                finish = finish or rm.get("finish_reason") or rm.get("stop_reason")
                u["messages"].append(_message(message))
            else:
                u["messages"].append({"role": "assistant", "content": g.text})
            if finish:
                u["finish"].append(str(finish))
    return u


class LlmTracingCallback(BaseCallbackHandler):
    def __init__(self, provider: str, model: str, role: str):
        self.provider = provider
        self.model = model
        self.role = role
        self._spans: dict[str, Any] = {}
        self._lock = threading.Lock()

    def _start(self, run_id, messages: list[dict[str, Any]]) -> None:
        if run_id is None:
            return
        try:
            s = get_tracer().start_span(
                f"chat {self.model}",
                kind=SpanKind.CLIENT,
                attributes={
                    sc.OPERATION_NAME: sc.OP_CHAT,
                    sc.PROVIDER_NAME: sc.PROVIDER_NAMES.get(self.provider, self.provider),
                    sc.REQUEST_MODEL: self.model,
                    sc.ROTOM_LLM_ROLE: self.role,
                },
            )
            with self._lock:
                self._spans[str(run_id)] = s
            set_content(s, sc.INPUT_MESSAGES, messages)
        except Exception:
            logger.warning("LLM span start failed", exc_info=True)

    def _pop(self, run_id):
        if run_id is None:
            return None
        with self._lock:
            return self._spans.pop(str(run_id), None)

    def on_chat_model_start(self, serialized, messages, *, run_id=None, **kwargs) -> None:
        self._start(run_id, [_message(m) for batch in messages for m in batch])

    def on_llm_start(self, serialized, prompts, *, run_id=None, **kwargs) -> None:
        self._start(run_id, [{"role": "user", "content": p} for p in prompts])

    def on_llm_end(self, response: LLMResult, *, run_id=None, **kwargs) -> None:
        s = self._pop(run_id)
        if s is None:
            return
        try:
            u = _usage(response)
            resp_model = u["model"] or self.model
            cost = cost_usd(self.provider, resp_model, input_tokens=u["input"],
                            output_tokens=u["output"], cache_read_tokens=u["cache_read"])
            if cost is None and resp_model != self.model:
                cost = cost_usd(self.provider, self.model, input_tokens=u["input"],
                                output_tokens=u["output"], cache_read_tokens=u["cache_read"])
            s.set_attribute(sc.RESPONSE_MODEL, resp_model)
            s.set_attribute(sc.USAGE_INPUT_TOKENS, int(u["input"]))
            s.set_attribute(sc.USAGE_OUTPUT_TOKENS, int(u["output"]))
            if u["cache_read"]:
                s.set_attribute(sc.USAGE_CACHE_READ_INPUT_TOKENS, int(u["cache_read"]))
            if u["reasoning"]:
                s.set_attribute(sc.USAGE_REASONING_OUTPUT_TOKENS, int(u["reasoning"]))
            if u["finish"]:
                s.set_attribute(sc.RESPONSE_FINISH_REASONS, u["finish"])
            if cost is not None:
                s.set_attribute(sc.ROTOM_COST_USD, cost)
            set_content(s, sc.OUTPUT_MESSAGES, u["messages"])
        except Exception:
            logger.warning("LLM span finish failed", exc_info=True)
        finally:
            s.end()

    def on_llm_error(self, error: BaseException, *, run_id=None, **kwargs) -> None:
        s = self._pop(run_id)
        if s is None:
            return
        try:
            s.record_exception(error)
            s.set_attribute(sc.ERROR_TYPE, type(error).__name__)
            s.set_status(Status(StatusCode.ERROR, str(error)[:500]))
        except Exception:
            logger.warning("LLM span error-finish failed", exc_info=True)
        finally:
            s.end()
