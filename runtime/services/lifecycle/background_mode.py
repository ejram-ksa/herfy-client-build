from __future__ import annotations

from dataclasses import dataclass
from typing import Callable


@dataclass(slots=True)
class BackgroundModeController:
    hide_window: Callable[[], None]
    show_window: Callable[[], None]
    pause_visual_refresh: Callable[[], None]
    resume_visual_refresh: Callable[[], None]

    def enter(self) -> None:
        self.pause_visual_refresh()
        self.hide_window()

    def leave(self) -> None:
        self.show_window()
        self.resume_visual_refresh()
