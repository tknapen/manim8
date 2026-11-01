"""Exact placement of moving objects: a member's points are its base points plus one offset (ADR-039).

`Mobject.shift` adds a vector to the points in place. An object shifted once per frame through ninety offsets
therefore ends one rounding away from the same object shifted once to the last offset: the same picture, but a
different Manim per-play hash, because the hash covers the points bit for bit. A play that Manim fast-forwards,
or serves from its cache or the segment store, applies its tracks once; a play it draws applies them every
frame. If the two leave different bits, every later play of a re-render, and of every part of a parallel
render, misses the segment store (ADR-033). Setting `base + offset` makes the points a function of the offset
alone, however many frames led there.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import numpy as np


def member_points(mobject: Any) -> list[np.ndarray]:
    """Copies of the points of every member of `mobject` that has points, in family order."""
    return [np.array(m.points, dtype=float) for m in mobject.family_members_with_points()]


def restore_points(mobject: Any, base: Sequence[np.ndarray], offset: np.ndarray | None = None) -> bool:
    """Set every member's points to its base points, plus `offset` when given. Returns False, changing nothing,
    when the object's structure no longer matches the base (a member gained or lost points)."""
    members = mobject.family_members_with_points()
    if len(members) != len(base) or any(m.points.shape != b.shape for m, b in zip(members, base, strict=True)):
        return False
    for member, points in zip(members, base, strict=True):
        member.points = points + offset if offset is not None else points.copy()
    return True


class Placement:
    """Moves a group by setting every member's points to its base points plus one offset.

    The base of a member is its points when the placement first saw it, less the offset then in force. A member
    that another track changed since the last placement (a curve redrawn by a sweep), or that joined the group
    since (a fresh readout), is rebased the same way, as it now is. A track that changes members of a moving
    group should therefore apply after the move within a frame and set them from the moved state, as sweeps do
    from their axes; `SnapshotScene.run_until` applies moves first.
    """

    __slots__ = ("_members", "group", "offset", "origin")
    """Bookkeeping, not picture: without a `__dict__`, Manim's per-play hash records only the class name, so the
    bases and the member ids (which differ between processes) never enter a segment's key; the points they
    produce do, through the mobjects."""

    def __init__(self, group: Any, origin: Sequence[float] | np.ndarray | None = None) -> None:
        self.group = group
        self.origin = np.zeros(3) if origin is None else np.array(origin, dtype=float)
        """Where the offset is measured from, for callers that place by position: a flat object's centre when its
        first move began, a sphere's world centre when it was built."""
        self.offset = np.zeros(3)
        self._members: dict[int, tuple[Any, np.ndarray, np.ndarray]] = {}
        """Per member id: the member, its base points and the points this placement last gave it."""

    def place(self, offset: Sequence[float] | np.ndarray) -> None:
        target = np.array(offset, dtype=float)
        members: dict[int, tuple[Any, np.ndarray, np.ndarray]] = {}
        for member in self.group.get_family():
            points = member.points
            if not len(points):
                continue
            known = self._members.get(id(member))
            if known is not None and known[0] is member and np.array_equal(known[2], points):
                base = known[1]
            else:
                base = points - self.offset  # exact for the zero offset a placement starts from
            placed = base + target
            member.points = placed
            members[id(member)] = (member, base, placed.copy())
        self._members = members
        self.offset = target
