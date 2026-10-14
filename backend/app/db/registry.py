"""Import every ``app.<domain>.models`` module so ``Base.metadata`` is fully populated.

Used by ``app/db/migrations/env.py`` and the test bootstrap. Adding a new domain with a
``models.py`` needs no registration anywhere — the walker finds it.
"""

import importlib
import pkgutil

import app


def register_all_models() -> None:
    for info in pkgutil.walk_packages(app.__path__, prefix="app."):
        if info.name.rsplit(".", 1)[-1] == "models":
            importlib.import_module(info.name)
