"""Model allowlist parsing and the catalog's availability, defaults and tiering."""

import pytest

from app.core.config import parse_model_id
from app.core.exceptions import AppError
from app.core.llm.catalog import ModelCatalog, model_catalog

MODELS = [
    "anthropic:claude-opus-5-5",
    "anthropic:claude-sonnet-5-5",
    "anthropic:claude-haiku-5-5",
    "openai:llama3.3",
    "openai:gpt-5.4-mini",
]


def _catalog(
    *,
    anthropic: bool = True,
    openai: bool = False,
    openai_tools: bool = False,
    native_search: bool = False,
    search: bool = False,
    sandbox: bool = False,
) -> ModelCatalog:
    return ModelCatalog(
        model_ids=MODELS,
        default_id="anthropic:claude-opus-5-5",
        title_id="anthropic:claude-haiku-5-5",
        anthropic_configured=anthropic,
        openai_configured=openai,
        openai_supports_tools=openai_tools,
        openai_supports_reasoning=False,
        openai_supports_vision=False,
        openai_native_web_search=native_search,
        search_configured=search,
        sandbox_configured=sandbox,
    )


class TestParseModelId:
    def test_accepts_provider_and_model(self) -> None:
        assert parse_model_id("anthropic:claude-opus-5-5") == ("anthropic", "claude-opus-5-5")
        assert parse_model_id("openai:llama3.3") == ("openai", "llama3.3")

    @pytest.mark.parametrize(
        "value",
        [
            "claude-opus-5-5",
            "anthropic:",
            "bedrock:claude",
            "anthropic:claude-opus-5-5-20260401",
            "openai:claude-opus-5-5",
        ],
    )
    def test_rejects_malformed_ids(self, value: str) -> None:
        with pytest.raises(ValueError, match="model"):
            parse_model_id(value)


class TestCatalog:
    def test_available_hides_unconfigured_providers(self) -> None:
        assert [spec.id for spec in _catalog().available()] == MODELS[:3]
        assert [spec.id for spec in _catalog(openai=True).available()] == MODELS
        assert _catalog(anthropic=False).available() == []

    def test_known_models_carry_display_names_and_prices(self) -> None:
        opus = _catalog().get("anthropic:claude-opus-5-5")
        assert (opus.display_name, opus.tier, opus.input_usd_per_mtok, opus.is_default) == (
            "Claude Opus 5.5",
            "frontier",
            4.0,
            True,
        )
        llama = _catalog(openai=True).get("openai:llama3.3")
        assert (llama.display_name, llama.supports_tools, llama.input_usd_per_mtok) == ("Llama3.3", False, None)

    def test_get_errors(self) -> None:
        with pytest.raises(AppError) as unknown:
            _catalog().get("anthropic:claude-opus-99")
        assert unknown.value.status_code == 400
        with pytest.raises(AppError) as unconfigured:
            _catalog().get("openai:llama3.3")
        assert unconfigured.value.status_code == 503

    def test_default_title_and_cheaper(self) -> None:
        catalog = _catalog(openai=True)
        assert catalog.default().id == "anthropic:claude-opus-5-5"
        assert catalog.title_model().id == "anthropic:claude-haiku-5-5"
        assert catalog.cheaper(catalog.default()).id == "anthropic:claude-sonnet-5-5"
        assert catalog.cheaper(catalog.title_model()).id == "anthropic:claude-haiku-5-5"
        assert catalog.cheaper(catalog.get("openai:llama3.3")).id == "openai:gpt-5.4-mini"
        assert catalog.cheaper(catalog.get("openai:gpt-5.4-mini")).id == "openai:gpt-5.4-mini"

    def test_defaults_fall_back_to_the_available_provider(self) -> None:
        catalog = _catalog(anthropic=False, openai=True)
        assert catalog.default().id == "openai:llama3.3"
        assert catalog.default().is_default is True
        assert catalog.get("anthropic:claude-opus-5-5" if False else "openai:gpt-5.4-mini").is_default is False
        assert catalog.title_model().id == "openai:gpt-5.4-mini"
        assert [spec.id for spec in catalog.available()] == ["openai:llama3.3", "openai:gpt-5.4-mini"]

    def test_configured_defaults_win_when_available(self) -> None:
        catalog = _catalog(openai=True)
        assert catalog.default().id == "anthropic:claude-opus-5-5"
        assert catalog.title_model().id == "anthropic:claude-haiku-5-5"

    def test_process_catalog_follows_the_test_environment(self) -> None:
        assert [spec.id for spec in model_catalog().available()] == MODELS[:3]


class TestCapabilities:
    """What a run on each model can do here: built-in search (OpenAI), Tavily search, the sandbox."""

    def test_openai_models_search_natively_when_the_flag_and_tools_are_on(self) -> None:
        gpt = _catalog(openai=True, openai_tools=True, native_search=True).get("openai:gpt-5.4-mini")
        assert (gpt.native_web_search, gpt.web_search, gpt.code) == (True, True, False)
        opus = _catalog(openai=True, openai_tools=True, native_search=True).get("anthropic:claude-opus-5-5")
        assert (opus.native_web_search, opus.web_search, opus.code) == (False, False, False)

    def test_tavily_and_the_sandbox_cover_every_tool_capable_model(self) -> None:
        catalog = _catalog(openai=True, openai_tools=True, search=True, sandbox=True)
        for model_id in ("anthropic:claude-opus-5-5", "openai:gpt-5.4-mini"):
            spec = catalog.get(model_id)
            assert (spec.native_web_search, spec.web_search, spec.code) == (False, True, True)

    def test_models_without_tool_support_get_nothing(self) -> None:
        llama = _catalog(openai=True, native_search=True, search=True, sandbox=True).get("openai:llama3.3")
        assert (llama.supports_tools, llama.native_web_search, llama.web_search, llama.code) == (
            False,
            False,
            False,
            False,
        )
