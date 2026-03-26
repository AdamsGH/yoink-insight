"""Command handler registration for the insight plugin.

Each module in this package exposes a register(app) function.
We collect handlers via a fake Application shim and wrap them in HandlerSpec.
"""
from __future__ import annotations

import importlib
import logging
import pkgutil
from pathlib import Path
from typing import Any

from telegram.ext import BaseHandler

from yoink.core.plugin import HandlerSpec

logger = logging.getLogger(__name__)

_PKG_DIR = Path(__file__).parent

_SKIP: set[str] = {"__init__"}


class _AppShim:
    """Minimal Application stand-in that collects add_handler() calls."""

    def __init__(self) -> None:
        self._specs: list[HandlerSpec] = []

    def add_handler(self, handler: BaseHandler, group: int = 0, **_: Any) -> None:
        self._specs.append(HandlerSpec(handler=handler, group=group))

    @property
    def specs(self) -> list[HandlerSpec]:
        return self._specs


def get_handler_specs() -> list[HandlerSpec]:
    """Import every command module and collect HandlerSpecs via their register()."""
    shim = _AppShim()
    for module_info in pkgutil.iter_modules([str(_PKG_DIR)]):
        name = module_info.name
        if name.startswith("_") or name in _SKIP:
            continue
        try:
            module = importlib.import_module(f"yoink_insight.commands.{name}")
            if hasattr(module, "register"):
                module.register(shim)
                logger.debug("Registered insight command module: %s", name)
        except Exception:
            logger.exception("Failed to register insight command module: %s", name)
    return shim.specs
