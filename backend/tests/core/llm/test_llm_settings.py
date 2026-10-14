"""Provider activation: a key activates OpenAI itself; a custom server needs none."""

from pydantic import SecretStr

from app.core.config import OPENAI_DEFAULT_BASE_URL, LlmSettings


def _settings(**overrides: object) -> LlmSettings:
    # Explicit kwargs outrank the process environment the test suite pins in conftest.py.
    return LlmSettings(**overrides)  # pyright: ignore[reportArgumentType]


class TestOpenAIActivation:
    def test_default_server_is_openai_and_needs_a_key(self) -> None:
        settings = _settings(openai_api_key=None, openai_base_url="")
        assert settings.openai_base_url == OPENAI_DEFAULT_BASE_URL
        assert settings.openai_configured is False

    def test_key_activates_openai(self) -> None:
        assert _settings(openai_api_key=SecretStr("sk-test"), openai_base_url="").openai_configured is True

    def test_custom_server_needs_no_key(self) -> None:
        settings = _settings(openai_api_key=None, openai_base_url="http://localhost:11434/v1/")
        assert settings.openai_base_url == "http://localhost:11434/v1"
        assert settings.openai_configured is True

    def test_capabilities_default_on(self) -> None:
        settings = _settings()
        assert (
            settings.llm_openai_supports_tools,
            settings.llm_openai_supports_reasoning,
            settings.llm_openai_supports_vision,
            settings.llm_openai_parallel_tool_calls,
        ) == (True, True, True, True)
