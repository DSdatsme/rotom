"""OpenTelemetry attribute names rotom emits — the ONE place they are spelled.

The OTel GenAI conventions are still "Development" stability; when upstream renames an
attribute, change it here (the version below is recorded in obs_meta). rotom-specific
attributes live under `rotom.*` so they never collide with upstream names.
"""

SEMCONV_VERSION = "gen-ai/1.42.0"

# --- GenAI (https://github.com/open-telemetry/semantic-conventions-genai) ---
OPERATION_NAME = "gen_ai.operation.name"
PROVIDER_NAME = "gen_ai.provider.name"
REQUEST_MODEL = "gen_ai.request.model"
RESPONSE_MODEL = "gen_ai.response.model"
RESPONSE_FINISH_REASONS = "gen_ai.response.finish_reasons"
USAGE_INPUT_TOKENS = "gen_ai.usage.input_tokens"
USAGE_OUTPUT_TOKENS = "gen_ai.usage.output_tokens"
USAGE_CACHE_READ_INPUT_TOKENS = "gen_ai.usage.cache_read.input_tokens"
USAGE_REASONING_OUTPUT_TOKENS = "gen_ai.usage.reasoning.output_tokens"
INPUT_MESSAGES = "gen_ai.input.messages"
OUTPUT_MESSAGES = "gen_ai.output.messages"
CONVERSATION_ID = "gen_ai.conversation.id"
AGENT_NAME = "gen_ai.agent.name"
TOOL_NAME = "gen_ai.tool.name"
TOOL_CALL_ARGUMENTS = "gen_ai.tool.call.arguments"
TOOL_CALL_RESULT = "gen_ai.tool.call.result"
ERROR_TYPE = "error.type"

OP_CHAT = "chat"
OP_INVOKE_AGENT = "invoke_agent"
OP_EXECUTE_TOOL = "execute_tool"

# Attributes holding captured content (shown specially in the dashboard).
CONTENT_ATTRIBUTES = (INPUT_MESSAGES, OUTPUT_MESSAGES, TOOL_CALL_ARGUMENTS, TOOL_CALL_RESULT)

# --- HTTP (stable OTel conventions) ---
HTTP_METHOD = "http.request.method"
HTTP_ROUTE = "http.route"
HTTP_STATUS_CODE = "http.response.status_code"
URL_PATH = "url.path"

# --- rotom ---
ROTOM_RUN_ID = "rotom.run.id"
ROTOM_RUN_KIND = "rotom.run.kind"
ROTOM_RUN_SOURCE = "rotom.run.source"
ROTOM_RUN_STATUS = "rotom.run.status"
ROTOM_RUN_SUMMARY = "rotom.run.summary"
ROTOM_LLM_ROLE = "rotom.llm.role"
ROTOM_COST_USD = "rotom.cost_usd"
ROTOM_LEGACY = "rotom.legacy"

# rotom provider id (MODEL_PROVIDER / model prefix) → gen_ai.provider.name value
PROVIDER_NAMES = {"gemini": "gcp.gemini", "anthropic": "anthropic", "groq": "groq"}
# rotom provider id → genai-prices provider id
PRICING_PROVIDERS = {"gemini": "google", "anthropic": "anthropic", "groq": "groq"}
