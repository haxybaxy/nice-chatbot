"""What each provider's request would look like — asserted on the payload builders, never on the network."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import replace
from typing import Protocol, cast
from uuid import uuid4

import pytest
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import BaseTool

from app.core.config import OPENAI_DEFAULT_BASE_URL
from app.core.exceptions import AppError
from app.core.llm.chat_models import (
    BuiltModel,
    DefaultChatModelFactory,
    ProviderConfig,
    ProviderTool,
    build_chat_model,
    default_chat_model_factory,
)
from app.core.tools.registry import NATIVE_WEB_SEARCH, default_tool_registry
from app.core.ui_stream import JsonObject
from tests.fakes_llm import GPT, HAIKU, LOCAL, OPUS, FakeSandboxClient, FakeSearchClient, make_run_context


class _PayloadBuilder(Protocol):
    def _get_request_payload(self, input_: Sequence[BaseMessage], **kwargs: object) -> dict[str, object]: ...


class _Bound(Protocol):
    @property
    def kwargs(self) -> Mapping[str, object]: ...


def _payload(
    built: BuiltModel, messages: Sequence[BaseMessage], tools: Sequence[BaseTool | ProviderTool] = ()
) -> dict[str, object]:
    """The provider request for ``messages`` as the agent node would send it (tools + invoke kwargs bound)."""
    bound = built.runnable(tools)
    kwargs: Mapping[str, object] = cast("_Bound", bound).kwargs if (tools or built.invoke_kwargs) else {}
    # The private payload builder is the only offline view of the wire request.
    return cast("_PayloadBuilder", built.model)._get_request_payload(list(messages), **kwargs)  # pyright: ignore[reportPrivateUsage]


def _config(**overrides: object) -> ProviderConfig:
    base = {
        "anthropic_api_key": "sk-ant-test",
        "anthropic_base_url": None,
        "openai_api_key": None,
        "openai_base_url": "http://localhost:11434/v1",
        "default_max_tokens": 4096,
        "request_timeout_s": 60.0,
        "max_retries": 2,
        "openai_max_tokens_param": "max_completion_tokens",
        "openai_parallel_tool_calls": False,
        "openai_responses_api": False,
    }
    return ProviderConfig(**cast("dict[str, object]", {**base, **overrides}))  # pyright: ignore[reportArgumentType] — test shorthand


def _json_dict(value: object) -> dict[str, object]:
    assert isinstance(value, dict)
    return cast("dict[str, object]", value)


def _json_list(value: object) -> list[dict[str, object]]:
    assert isinstance(value, list)
    return [_json_dict(item) for item in cast("list[object]", value)]


def _tools() -> list[BaseTool]:
    ctx = make_run_context(search=FakeSearchClient(), sandbox=FakeSandboxClient())
    return list(default_tool_registry().for_run(ctx, names={"web_search", "run_code"}, spec=OPUS).client)


SYSTEM_BLOCKS = SystemMessage(
    content=[
        {"type": "text", "text": "stable", "cache_control": {"type": "ephemeral"}},
        {"type": "text", "text": "volatile"},
    ]
)


class TestAnthropic:
    def test_request_shape(self) -> None:
        user_id = uuid4()
        built = build_chat_model(OPUS, _config(), effort="high", purpose="chat", user_id=user_id)
        payload = _payload(built, [SYSTEM_BLOCKS, HumanMessage("hi")], _tools())

        assert payload["model"] == "claude-opus-5-5"
        assert payload["max_tokens"] == 4096
        assert payload["thinking"] == {"type": "adaptive", "display": "summarized"}
        assert payload["output_config"] == {"effort": "high"}
        assert payload["cache_control"] == {"type": "ephemeral"}
        assert payload["metadata"] == {"user_id": str(user_id)}
        assert payload["system"] == [
            {"type": "text", "text": "stable", "cache_control": {"type": "ephemeral"}},
            {"type": "text", "text": "volatile"},
        ]
        for forbidden in ("temperature", "top_p", "top_k", "tool_choice", "budget_tokens"):
            assert forbidden not in payload
        tools = _json_list(payload["tools"])
        assert [tool["name"] for tool in tools] == ["run_code", "web_search"]
        search = tools[1]
        assert search["strict"] is True
        assert search["eager_input_streaming"] is True
        schema = _json_dict(search["input_schema"])
        properties = {name: _json_dict(prop) for name, prop in _json_dict(schema["properties"]).items()}
        assert schema["additionalProperties"] is False
        assert "maxLength" not in properties["query"]
        assert "minimum" not in properties["max_results"]
        required = schema["required"]
        assert isinstance(required, list)
        assert set(cast("list[str]", required)) == set(properties)
        assert built.system_format == "blocks"
        assert built.spec is OPUS

    def test_model_options_and_tags(self) -> None:
        built = build_chat_model(HAIKU, _config(), effort="low", purpose="title", max_tokens=512, silent=True)
        assert built.model.tags == ["purpose:title", "nostream"]
        assert built.model.metadata is not None
        assert built.model.metadata["purpose"] == "title"
        payload = _payload(built, [HumanMessage("t")])
        assert payload["max_tokens"] == 512
        assert "metadata" not in payload  # no user id given

    def test_output_schema_becomes_output_config_format(self) -> None:
        schema: JsonObject = {"type": "object", "properties": {"title": {"type": "string"}}, "required": ["title"]}
        built = build_chat_model(HAIKU, _config(), effort="low", purpose="title", output_schema=schema)
        payload = _payload(built, [HumanMessage("t")])
        assert payload["output_config"] == {"effort": "low", "format": {"type": "json_schema", "schema": schema}}

    def test_base_url_timeout_and_retries(self) -> None:
        built = build_chat_model(
            OPUS,
            _config(anthropic_base_url="https://proxy.example/anthropic", max_retries=5),
            effort="medium",
            purpose="chat",
        )
        model = cast("Mapping[str, object]", built.model.model_dump())
        assert model["anthropic_api_url"] == "https://proxy.example/anthropic"
        assert model["max_retries"] == 5
        assert model["default_request_timeout"] == 60.0
        assert model["stream_usage"] is True

    def test_missing_key_is_503(self) -> None:
        with pytest.raises(AppError) as error:
            build_chat_model(OPUS, _config(anthropic_api_key=None), effort="medium", purpose="chat")
        assert error.value.status_code == 503


def _openai_config(**overrides: object) -> ProviderConfig:
    """OpenAI itself: a key, the default base URL and the Responses API."""
    base: dict[str, object] = {
        "openai_api_key": "sk-test",
        "openai_base_url": OPENAI_DEFAULT_BASE_URL,
        "openai_parallel_tool_calls": True,
        "openai_responses_api": True,
    }
    return _config(**{**base, **overrides})


class TestOpenAIResponses:
    """api.openai.com: the Responses API, stateless, with the built-in web search bound as a provider tool."""

    def test_request_shape_for_openai_itself(self) -> None:
        built = build_chat_model(GPT, _openai_config(), effort="max", purpose="chat")
        run_tools = default_tool_registry().for_run(
            make_run_context(sandbox=FakeSandboxClient()), names={"run_code", "web_search"}, spec=GPT
        )
        payload = _payload(built, [SystemMessage("sys"), HumanMessage("hi")], run_tools.bound)

        assert payload["model"] == "gpt-5.5"
        assert "messages" not in payload
        input_items = _json_list(payload["input"])
        assert input_items[-1]["role"] == "user"
        assert payload["max_output_tokens"] == 4096
        assert payload["reasoning"] == {"effort": "xhigh", "summary": "auto"}
        assert payload["store"] is False
        assert payload["include"] == ["reasoning.encrypted_content", "web_search_call.action.sources"]
        assert payload["parallel_tool_calls"] is True
        for forbidden in (
            "max_completion_tokens",
            "reasoning_effort",
            "tool_choice",
            "temperature",
            "user",
            "extra_body",
        ):
            assert forbidden not in payload
        tools = _json_list(payload["tools"])
        # Responses shape: function tools are flat, the provider tool passes through untouched.
        assert [tool["type"] for tool in tools] == ["function", "web_search"]
        assert tools[0]["name"] == "run_code"
        assert "function" not in tools[0]
        assert "strict" not in tools[0]
        assert tools[1] == NATIVE_WEB_SEARCH
        model = cast("Mapping[str, object]", built.model.model_dump())
        assert model["use_responses_api"] is True
        assert model["openai_api_base"] == OPENAI_DEFAULT_BASE_URL
        assert built.system_format == "text"

    def test_legacy_max_tokens_name_is_ignored_on_the_responses_api(self) -> None:
        built = build_chat_model(
            GPT, _openai_config(openai_max_tokens_param="max_tokens"), effort="low", purpose="chat"
        )
        payload = _payload(built, [HumanMessage("hi")])
        assert payload["max_output_tokens"] == 4096
        assert "extra_body" not in payload

    def test_output_schema_becomes_text_format(self) -> None:
        schema: JsonObject = {"type": "object", "properties": {"title": {"type": "string"}}, "required": ["title"]}
        built = build_chat_model(
            GPT, _openai_config(), effort="low", purpose="title", output_schema=schema, silent=True
        )
        payload = _payload(built, [HumanMessage("hi")])
        assert "response_format" not in payload
        text_format = _json_dict(_json_dict(payload["text"])["format"])
        assert text_format["type"] == "json_schema"
        assert text_format["schema"] == schema
        assert "nostream" in (built.model.tags or [])

    def test_chat_completions_history_replays_as_responses_input(self) -> None:
        """Turns stored before the switch (string content + tool calls) still convert to input items."""
        built = build_chat_model(GPT, _openai_config(), effort="medium", purpose="chat")
        history: list[BaseMessage] = [
            HumanMessage("q"),
            AIMessage(
                content="",
                tool_calls=[{"name": "web_search", "args": {"query": "x"}, "id": "call_1", "type": "tool_call"}],
            ),
            ToolMessage(content="[1] result", tool_call_id="call_1", name="web_search"),
            AIMessage(content="ok [1]."),
            HumanMessage("next"),
        ]
        input_items = _json_list(_payload(built, history)["input"])
        call = next(item for item in input_items if item.get("type") == "function_call")
        assert (call["name"], call["call_id"]) == ("web_search", "call_1")
        output = next(item for item in input_items if item.get("type") == "function_call_output")
        assert (output["call_id"], output["output"]) == ("call_1", "[1] result")
        answer = next(item for item in input_items if item.get("type") == "message" and item.get("role") == "assistant")
        assert _json_list(answer["content"])[0]["text"] == "ok [1]."


class TestOpenAICompatible:
    def test_request_shape_for_a_local_server(self) -> None:
        built = build_chat_model(LOCAL, _config(openai_max_tokens_param="max_tokens"), effort="medium", purpose="chat")
        payload = _payload(built, [SystemMessage("sys"), HumanMessage("hi")], _tools())

        assert payload["model"] == "llama3.3"
        assert payload["extra_body"] == {"max_tokens": 4096}
        assert "max_completion_tokens" not in payload
        assert "reasoning_effort" not in payload  # LOCAL does not support reasoning
        for forbidden in ("tool_choice", "temperature", "user", "parallel_tool_calls", "cache_control", "thinking"):
            assert forbidden not in payload
        tools = _json_list(payload["tools"])
        functions = [_json_dict(tool["function"]) for tool in tools]
        assert [function["name"] for function in functions] == ["run_code", "web_search"]
        assert "strict" not in functions[1]
        assert "eager_input_streaming" not in tools[1]
        assert "eager_input_streaming" not in functions[1]
        messages = _json_list(payload["messages"])
        assert messages[0] == {"role": "system", "content": "sys"}
        assert built.system_format == "text"
        model = cast("Mapping[str, object]", built.model.model_dump())
        assert model["openai_api_base"] == "http://localhost:11434/v1"
        assert model["stream_usage"] is True
        assert model["use_responses_api"] is False
        assert model["disabled_params"] == {"parallel_tool_calls": None}

    def test_max_completion_tokens_reasoning_and_parallel_calls_when_supported(self) -> None:
        reasoning_spec = replace(LOCAL, supports_reasoning=True)
        built = build_chat_model(
            reasoning_spec,
            _config(openai_parallel_tool_calls=True, openai_api_key="sk-local"),
            effort="max",
            purpose="chat",
        )
        payload = _payload(built, [HumanMessage("hi")], _tools())
        assert payload["max_completion_tokens"] == 4096
        assert payload["reasoning_effort"] == "xhigh"
        assert payload["parallel_tool_calls"] is True
        assert "extra_body" not in payload
        model = cast("Mapping[str, object]", built.model.model_dump())
        assert model["disabled_params"] is None

    def test_output_schema_becomes_response_format_on_each_call(self) -> None:
        schema: JsonObject = {"type": "object", "properties": {"title": {"type": "string"}}, "required": ["title"]}
        built = build_chat_model(LOCAL, _config(), effort="low", purpose="title", output_schema=schema, silent=True)
        payload = _payload(built, [HumanMessage("t")])
        assert payload["response_format"] == {
            "type": "json_schema",
            "json_schema": {"name": "output", "schema": schema},
        }
        assert built.model.tags == ["purpose:title", "nostream"]

    def test_openai_itself_without_a_key_is_503(self) -> None:
        config = _config(openai_base_url=OPENAI_DEFAULT_BASE_URL, openai_api_key=None)
        with pytest.raises(AppError) as error:
            build_chat_model(LOCAL, config, effort="medium", purpose="chat")
        assert error.value.status_code == 503
        # A key activates OpenAI itself; a custom server never needed one.
        build_chat_model(
            LOCAL,
            _config(openai_base_url=OPENAI_DEFAULT_BASE_URL, openai_api_key="sk-test"),
            effort="medium",
            purpose="chat",
        )
        build_chat_model(
            LOCAL,
            _config(openai_base_url="http://localhost:11434/v1", openai_api_key=None),
            effort="medium",
            purpose="chat",
        )


class TestFactory:
    def test_default_factory_follows_the_test_environment(self) -> None:
        factory = default_chat_model_factory()
        built = factory.build(OPUS, effort="medium", purpose="chat")
        assert built.spec.id == "anthropic:claude-opus-5-5"
        with pytest.raises(AppError) as error:
            factory.build(LOCAL, effort="medium", purpose="chat")
        assert error.value.status_code == 503

    def test_explicit_factory(self) -> None:
        built = DefaultChatModelFactory(_config()).build(LOCAL, effort="low", purpose="research_task", max_tokens=100)
        assert _payload(built, [HumanMessage("x")])["max_completion_tokens"] == 100
