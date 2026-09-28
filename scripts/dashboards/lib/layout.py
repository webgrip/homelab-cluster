from __future__ import annotations

from .panels import grid_pos, row


class Grid:
    WIDTH = 24

    def __init__(self):
        self.panels = []
        self.y = 0
        self._band_w = 0
        self._band_h = 0
        self._collapsed_into = None

    def _close_band(self):
        if self._band_w:
            self.y += self._band_h
        self._band_w = self._band_h = 0

    def row(self, title, collapsed=True):
        self._close_band()
        section = row(title, self.y, collapsed)
        self.panels.append(section)
        self._collapsed_into = section["panels"] if collapsed else None
        self.y += 1
        return section

    def place(self, panel, x, w, h):
        if x + w > self.WIDTH:
            raise ValueError(f"{panel.get('title')!r} ends at column {x + w}, past {self.WIDTH}")
        if x == 0 and self._band_w:
            self._close_band()
        panel["gridPos"] = grid_pos(x, self.y, w, h)
        self._band_w += w
        self._band_h = max(self._band_h, h)
        (self._collapsed_into if self._collapsed_into is not None else self.panels).append(panel)
        return panel

    @property
    def height(self):
        return self.y + self._band_h


def walk(panels):
    for panel in panels:
        yield panel
        yield from walk(panel.get("panels") or [])


def number(panels):
    for panel_id, panel in enumerate(walk(panels), start=1):
        panel["id"] = panel_id
    return panels


def screen_height(panels):
    return max((p["gridPos"]["y"] + p["gridPos"]["h"] for p in panels), default=0)
