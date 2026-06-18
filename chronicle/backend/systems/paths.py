"""Static path network between buildings (Day 8 / visual flavor).

Generates a connected dirt-road network linking every building's entrance once
at world generation, persisted alongside the tile grid in ``region_static`` (see
``database.save_region_paths``). Like the decoration layer this is purely
cosmetic: paths carry no simulation meaning, never change after generation, and
are surfaced read-only in the render payload for the frontend to draw with the
kenney dirt tile.

The network is a minimum spanning tree over the building doors (so the whole
town is connected with the least road), with each MST edge realised as a BFS
shortest path over walkable, non-building, non-water ground - so roads weave
around structures and the river instead of cutting through them. Deterministic:
the same region always yields the same roads.
"""

from __future__ import annotations

from collections import deque
from typing import Any, Optional

# Ground a road may run over: open, passable terrain (and the stone door tiles).
# Building walls/floors and water are excluded, so roads route around them.
_ROAD_WALKABLE = {"grass", "dirt", "stone_path"}


def _doors(region: dict[str, Any]) -> list[tuple[int, int]]:
    """Each building's entrance tile (bottom-centre), matching world_gen."""
    doors: list[tuple[int, int]] = []
    for b in region.get("buildings", []) or []:
        dx = int(b["x"]) + int(b["width"]) // 2
        dy = int(b["y"]) + int(b["height"]) - 1
        doors.append((dx, dy))
    return doors


def _walkable_grid(region: dict[str, Any]) -> tuple[list[list[bool]], int, int]:
    tiles = region.get("tiles") or []
    height = len(tiles)
    width = len(tiles[0]) if height else 0
    walk = [[False] * width for _ in range(height)]
    for row in tiles:
        for tile in row:
            if tile.get("tile_type") in _ROAD_WALKABLE and tile.get("passable", False):
                walk[int(tile["y"])][int(tile["x"])] = True
    return walk, width, height


def _bfs(
    walk: list[list[bool]], width: int, height: int,
    start: tuple[int, int], goal: tuple[int, int],
) -> Optional[list[tuple[int, int]]]:
    """Shortest 4-neighbour route over walkable tiles, or None if unreachable."""
    if start == goal:
        return [start]
    prev: dict[tuple[int, int], Optional[tuple[int, int]]] = {start: None}
    queue: deque[tuple[int, int]] = deque([start])
    while queue:
        cx, cy = queue.popleft()
        if (cx, cy) == goal:
            break
        for dx, dy in ((0, -1), (0, 1), (-1, 0), (1, 0)):
            nx, ny = cx + dx, cy + dy
            if 0 <= nx < width and 0 <= ny < height and walk[ny][nx] and (nx, ny) not in prev:
                prev[(nx, ny)] = (cx, cy)
                queue.append((nx, ny))
    if goal not in prev:
        return None
    route: list[tuple[int, int]] = []
    node: Optional[tuple[int, int]] = goal
    while node is not None:
        route.append(node)
        node = prev[node]
    return route[::-1]


def _mst_edges(points: list[tuple[int, int]]) -> list[tuple[int, int]]:
    """Prim's MST (Manhattan distance) over the door points -> index pairs."""
    n = len(points)
    if n <= 1:
        return []
    in_tree = [False] * n
    in_tree[0] = True
    best_dist = [abs(points[i][0] - points[0][0]) + abs(points[i][1] - points[0][1]) for i in range(n)]
    best_from = [0] * n
    edges: list[tuple[int, int]] = []
    for _ in range(n - 1):
        pick = -1
        pick_d = 1 << 30
        for i in range(n):
            if not in_tree[i] and best_dist[i] < pick_d:
                pick_d = best_dist[i]
                pick = i
        if pick < 0:
            break
        edges.append((best_from[pick], pick))
        in_tree[pick] = True
        for i in range(n):
            if not in_tree[i]:
                d = abs(points[i][0] - points[pick][0]) + abs(points[i][1] - points[pick][1])
                if d < best_dist[i]:
                    best_dist[i] = d
                    best_from[i] = pick
    return edges


def generate_paths(region: dict[str, Any]) -> list[dict[str, int]]:
    """Return a deterministic list of ``{x, y}`` road tiles connecting building
    doors. Tiles are unique and row-major sorted, so repeated calls match."""
    doors = _doors(region)
    if len(doors) < 2:
        return []
    walk, width, height = _walkable_grid(region)
    road_tiles: set[tuple[int, int]] = set()
    for a, b in _mst_edges(doors):
        route = _bfs(walk, width, height, doors[a], doors[b])
        if route:
            road_tiles.update(route)
    return [{"x": x, "y": y} for (x, y) in sorted(road_tiles)]
