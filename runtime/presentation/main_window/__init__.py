from __future__ import annotations
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .window import HerfyMainWindow, MainWindow
__all__ = ["HerfyMainWindow", "MainWindow"]


def __getattr__(name: str):
    if name in __all__:
        from .window import HerfyMainWindow, MainWindow

        values = {"HerfyMainWindow": HerfyMainWindow, "MainWindow": MainWindow}
        return values[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
