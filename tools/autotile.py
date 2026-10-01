#!/usr/bin/env python3
"""Ground tile ids the way the course editor writes them.

A ground record's id is an auto-tile index: which of its 8 neighbours are
ground. It is the same index in every style; each style draws its own art
for it. Measured on 140 editor-made courses (SMB1, SMB3, SMW, NSMBU and one
3D World course, about 330k tiles): for each neighbour pattern the majority
id is the same in every style, and the 47 patterns of a blob tileset map one
to one onto ids 24-70. Ids 0-23 are the editor's random look-alikes of the
common ones (9-11 for a top 59, 12-14 for an interior 62, ...), which only
decorate, so none are written here.

The game draws a stored id as it is and recomputes it only around an edit
in the editor (a generated course edited there keeps the generator's ids
on every tile the edit did not touch), so a wrong id shows. In SMB1 the
ground's tops, walls and interior look alike and hide it; in SMW a top
written as interior has no grass and a wall written as interior no edge.

A corner neighbour counts only when both edges beside it are ground (UL
needs U and L), so the key is the edges present plus the corners missing.
The editor also counts ground that has no record: below row 0, past the
area's left, right and top edges, and the start and goal areas. Below row 0
is built in; the caller says the rest. With those, these ids match the
editor's (variants folded) on 97-99% of the tiles in every style that sit
away from objects; next to slopes, pipes and the like the editor tiles
against the object too, which this does not model.
"""

from typing import Callable, Dict, Iterable, Tuple

GROUND_IDS = {
    '': 24, 'R': 25, 'LR': 26, 'L': 27,
    'D': 28, 'U': 30, 'UD': 29,
    'DR': 58, 'DR-DR': 34,
    'DLR': 59, 'DLR-DL': 44, 'DLR-DR': 45, 'DLR-DL-DR': 36,
    'DL': 60, 'DL-DL': 33,
    'UR': 64, 'UR-UR': 32,
    'ULR': 65, 'ULR-UL': 46, 'ULR-UR': 47, 'ULR-UL-UR': 35,
    'UL': 66, 'UL-UL': 31,
    'UDR': 61, 'UDR-UR': 40, 'UDR-DR': 42, 'UDR-UR-DR': 38,
    'UDL': 63, 'UDL-UL': 41, 'UDL-DL': 43, 'UDL-UL-DL': 37,
    'UDLR': 62,
    'UDLR-UL': 67, 'UDLR-UR': 68, 'UDLR-DL': 69, 'UDLR-DR': 70,
    'UDLR-UL-UR': 52, 'UDLR-UL-DL': 54, 'UDLR-UL-DR': 57,
    'UDLR-UR-DL': 56, 'UDLR-UR-DR': 55, 'UDLR-DL-DR': 53,
    'UDLR-UL-UR-DL': 48, 'UDLR-UL-UR-DR': 49,
    'UDLR-UL-DL-DR': 50, 'UDLR-UR-DL-DR': 51,
    'UDLR-UL-UR-DL-DR': 39,
}


def autotile_ground(positions: Iterable[Tuple[int, int]],
                    outside: Callable[[int, int], bool] = lambda x, y: False
                    ) -> Dict[Tuple[int, int], int]:
    """The id of each ground position. `outside(x, y)` says whether a cell
    without a ground record is solid anyway; below row 0 always is."""
    cells = set(positions)

    def solid(x, y):
        return y < 0 or (x, y) in cells or outside(x, y)

    ids = {}
    for (x, y) in cells:
        u, d, l, r = solid(x, y + 1), solid(x, y - 1), solid(x - 1, y), solid(x + 1, y)
        key = ''.join(n for n, v in (('U', u), ('D', d), ('L', l), ('R', r)) if v)
        for name, edges, dx, dy in (('UL', u and l, -1, 1), ('UR', u and r, 1, 1),
                                    ('DL', d and l, -1, -1), ('DR', d and r, 1, -1)):
            if edges and not solid(x + dx, y + dy):
                key += '-' + name
        ids[(x, y)] = GROUND_IDS[key]
    return ids
