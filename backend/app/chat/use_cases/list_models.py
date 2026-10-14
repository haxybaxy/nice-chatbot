from app.core.llm.catalog import ModelSpec, model_catalog


class ListModels:
    """The model picker: every allowlisted model whose provider is configured."""

    def __init__(self) -> None:
        self._catalog = model_catalog()

    async def execute(self) -> list[ModelSpec]:
        return self._catalog.available()
