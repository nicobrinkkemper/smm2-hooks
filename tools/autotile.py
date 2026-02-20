#!/usr/bin/env python3
"""
Auto-tiling implementation based on observed SMM2 patterns.

The game uses neighbor-aware tile selection. Each tile ID encodes
which neighbors exist:
- 4 cardinal directions (up/down/left/right)
- Possibly 4 diagonal directions
- Style-specific variations (3DW vs 2D styles)

This is a reverse-engineered approximation based on Nico's hand-edited levels.
The actual game logic is in the 0x7100E7xxxx-0x7100EDxxxx region (not yet decompiled).

TODO: Decompile the actual tile selection functions:
- sub_7100E7FD90 (4140B) - enum registration, not selection
- sub_7100ED4710 (1708B) - near EditGrassField  
- EditGroundBox methods around 0x7100ED7800
"""

from enum import IntFlag
from typing import Dict, Tuple, Set

class Neighbor(IntFlag):
    """Neighbor bitmask for tile selection."""
    NONE = 0
    LEFT = 1
    RIGHT = 2
    UP = 4
    DOWN = 8
    # Diagonals (may be used for corner detection)
    UP_LEFT = 16
    UP_RIGHT = 32
    DOWN_LEFT = 64
    DOWN_RIGHT = 128


# Observed tile IDs from hand-edited levels
# VERIFIED 2026-02-19 via live testing with Eden

# 2D Styles (SMB1, SMB3, SMW, NSMBU)
TILE_2D = {
    # Single-row tiles (1 block tall, no UP or DOWN neighbor)
    'single_left': 25,       # No LEFT, no UP, no DOWN
    'single_mid': 26,        # Has LEFT and RIGHT, no UP, no DOWN
    'single_right': 27,      # No RIGHT, no UP, no DOWN
    
    # Surface row (top edge, has DOWN but no UP neighbor)
    'surface_left': 58,      # No LEFT
    'surface_mid': 59,       # Has LEFT and RIGHT
    'surface_right': 60,     # No RIGHT
    'surface_single': 58,    # No LEFT or RIGHT (but has DOWN)
    
    # Fill rows (middle, has both UP and DOWN neighbors)
    'fill_left': 61,         # No LEFT
    'fill_mid': 62,          # Has LEFT and RIGHT  
    'fill_right': 63,        # No RIGHT
    'fill_single': 61,       # No LEFT or RIGHT
    
    # Bottom row (bottom edge, has UP but no DOWN neighbor)
    'bottom_left': 64,       # No LEFT, no DOWN
    'bottom_mid': 65,        # Has LEFT and RIGHT, no DOWN
    'bottom_right': 66,      # No RIGHT, no DOWN
    'bottom_single': 64,     # No LEFT or RIGHT (but has UP)
    
    # Special edges (may need more RE)
    'right_y3': 68,          # Right edge at y=surface-1
}

# 3DW Style (different visual treatment)
TILE_3DW = {
    'surface_left': 10,      # Different from 2D!
    'surface_mid': 59,
    'surface_right': 60,
    'surface_pre_right': 10, # Second-to-last before right edge
    
    'fill_left': 62,         # 3DW uses variation
    'fill_mid': 62,
    'fill_right': 62,        # Less specialized edges
    'fill_variation': 12,    # Scattered for texture
    'fill_detail': 13,       # Interior detail
    
    'right_y3': 68,
}


def get_neighbor_mask(tile_map: Set[Tuple[int, int]], x: int, y: int) -> int:
    """Calculate neighbor bitmask for a position."""
    mask = 0
    if (x-1, y) in tile_map: mask |= Neighbor.LEFT
    if (x+1, y) in tile_map: mask |= Neighbor.RIGHT
    if (x, y+1) in tile_map: mask |= Neighbor.UP
    if (x, y-1) in tile_map: mask |= Neighbor.DOWN
    if (x-1, y+1) in tile_map: mask |= Neighbor.UP_LEFT
    if (x+1, y+1) in tile_map: mask |= Neighbor.UP_RIGHT
    if (x-1, y-1) in tile_map: mask |= Neighbor.DOWN_LEFT
    if (x+1, y-1) in tile_map: mask |= Neighbor.DOWN_RIGHT
    return mask


def select_tile_2d(mask: int, at_level_top: bool = False, at_level_left: bool = False) -> int:
    """Select tile ID for 2D styles based on 8-neighbor mask.
    
    Tile selection logic (verified 2026-02-20 with complex shapes):
    - Single-row (no UP, no DOWN): tiles 25-27 (+ texture variations 6,7,8)
    - Surface (no UP, has DOWN): tiles 58-60
    - Fill (has UP, has DOWN): tiles 61-63 (+ texture variations 12,13,14)
    - Bottom (has UP, no DOWN): tiles 64-66
    
    Level boundaries:
    - At level top (y=26/27): Surface treated as fill (boundary = neighbor above)
    - At level left (x=0): Left edge uses right-edge tiles (boundary = neighbor left)
    
    Diagonal neighbors affect corner tiles and texture variations.
    """
    import random
    
    # Original mask values (before boundary adjustment)
    orig_has_left = bool(mask & Neighbor.LEFT)
    orig_has_right = bool(mask & Neighbor.RIGHT)
    orig_has_up = bool(mask & Neighbor.UP)
    orig_has_down = bool(mask & Neighbor.DOWN)
    
    has_left = orig_has_left
    has_right = orig_has_right
    has_up = orig_has_up
    has_down = orig_has_down
    has_ul = bool(mask & Neighbor.UP_LEFT)
    has_ur = bool(mask & Neighbor.UP_RIGHT)
    has_dl = bool(mask & Neighbor.DOWN_LEFT)
    has_dr = bool(mask & Neighbor.DOWN_RIGHT)
    
    # Original row type (before boundary adjustment)
    orig_is_surface = not orig_has_up and orig_has_down
    orig_is_single = not orig_has_up and not orig_has_down
    
    # Special boundary tiles (check BEFORE adjustment)
    # Tile 70: top-left corner of level (surface at boundary)
    if at_level_top and at_level_left and orig_is_surface:
        return 70
    # Tile 43: at level top with UL+R+DR pattern (mask 0x89)
    if at_level_top and (mask == 0x89):
        return 43
    # Tile 47: bottom tile at left boundary
    if at_level_left and orig_has_up and not orig_has_down and not orig_has_left:
        return 47
    # Tile 32: mask 0x06 (DL+D) or 0x96 (UL+L+DL+D) - corner pattern
    if mask in [0x06, 0x96]:
        return 32
    # Tile 33: mask 0x09 (R+DR) or 0x19 (L+R+DR)
    if mask in [0x09, 0x19]:
        return 33
    
    # Level boundary adjustments for row type determination
    if at_level_top:
        has_up = True  # Level boundary acts as neighbor above
    if at_level_left:
        has_left = True  # Level boundary acts as neighbor left
    
    # Determine row type based on adjusted vertical neighbors
    is_single = not has_up and not has_down
    is_surface = not has_up and has_down
    is_bottom = has_up and not has_down
    is_fill = has_up and has_down
    
    if is_single:
        # Single-row tiles (1 block tall floating)
        # At level top, single rows use alternating 15/16/65 pattern
        if at_level_top and has_left and has_right:
            return random.choice([15, 16, 65])
        if not has_left and not has_right:
            return TILE_2D['single_left']  # Single isolated block
        elif not has_left:
            return TILE_2D['single_left']
        elif not has_right:
            return TILE_2D['single_right']
        else:
            # Middle of single row - add texture variation
            if random.random() < 0.3:
                return random.choice([6, 7, 8])
            return TILE_2D['single_mid']
    
    elif is_surface:
        # Top surface row
        if not has_left and not has_right:
            return TILE_2D['surface_single']
        elif not has_left:
            return TILE_2D['surface_left']
        elif not has_right:
            return TILE_2D['surface_right']
        else:
            return TILE_2D['surface_mid']
    
    elif is_bottom:
        # Bottom row check - if tile has both UL and UR diagonals, treat as fill not bottom
        # The game uses fill (62) at ground level instead of bottom tiles (64-66)
        # when the row is well-connected horizontally
        if has_ul and has_ur:
            # Well-connected row - use fill tiles
            if not has_left:
                return TILE_2D['fill_left']
            elif not has_right:
                return TILE_2D['fill_right']
            else:
                return TILE_2D['fill_mid']
        # True bottom edge
        if not has_left and not has_right:
            return TILE_2D['bottom_single']
        elif not has_left:
            return TILE_2D['bottom_left']
        elif not has_right:
            return TILE_2D['bottom_right']
        else:
            return TILE_2D['bottom_mid']
    
    else:
        # Fill rows (middle)
        if not has_left and not has_right:
            # Vertical column
            return 29  # Special vertical column tile
        elif not has_left:
            # Left edge
            return TILE_2D['fill_left']
        elif not has_right:
            # Right edge - special variant for missing UR diagonal at row boundary
            if not has_ur and not has_dr:
                return 68  # Right edge special
            return TILE_2D['fill_right']
        else:
            # Interior fill - texture variation
            if random.random() < 0.3:
                return random.choice([12, 13, 14])
            return TILE_2D['fill_mid']


def select_tile_3dw(mask: int, is_surface: bool, x: int, max_x: int) -> int:
    """Select tile ID for 3DW style with texture variation."""
    import random
    
    has_left = bool(mask & Neighbor.LEFT)
    has_right = bool(mask & Neighbor.RIGHT)
    
    if is_surface:
        if not has_left:
            return TILE_3DW['surface_left']
        elif not has_right:
            return TILE_3DW['surface_right']
        elif x == max_x - 1:
            return TILE_3DW['surface_pre_right']
        else:
            return TILE_3DW['surface_mid']
    else:
        # Fill with random variation for 3DW texture
        if random.random() < 0.25:
            return TILE_3DW['fill_variation'] if random.random() < 0.8 else TILE_3DW['fill_detail']
        return TILE_3DW['fill_mid']


def autotile_ground(positions: Set[Tuple[int, int]], style: str = 'SMB1', 
                    level_bounds: Tuple[int, int, int, int] = None) -> Dict[Tuple[int, int], int]:
    """
    Generate tile IDs for a set of ground positions.
    
    Args:
        positions: Set of (x, y) coordinates where ground exists
        style: Game style ('SMB1', 'SMB3', 'SMW', 'NSMBU', '3DW')
        level_bounds: Optional (min_x, max_x, min_y, max_y) for boundary detection
    
    Returns:
        Dict mapping (x, y) -> tile_id
    """
    if not positions:
        return {}
    
    result = {}
    
    # Find bounds from positions if not provided
    min_x = min(p[0] for p in positions)
    max_x = max(p[0] for p in positions)
    min_y = min(p[1] for p in positions)
    max_y = max(p[1] for p in positions)
    
    # Use level bounds if provided (for boundary tile detection)
    if level_bounds:
        lvl_min_x, lvl_max_x, lvl_min_y, lvl_max_y = level_bounds
    else:
        lvl_min_x, lvl_max_x, lvl_min_y, lvl_max_y = min_x, max_x, min_y, max_y
    
    is_3dw = style == '3DW'
    
    for (x, y) in positions:
        mask = get_neighbor_mask(positions, x, y)
        
        # Level boundary detection - boundaries act like neighbors exist
        at_level_top = (y == lvl_max_y) or (y >= 26)  # y=26/27 is level top
        at_level_left = (x == lvl_min_x) or (x == 0)  # x=0 is level left
        
        if is_3dw:
            is_surface = not bool(mask & Neighbor.UP)
            tile_id = select_tile_3dw(mask, is_surface, x, max_x)
        else:
            tile_id = select_tile_2d(mask, at_level_top, at_level_left)
        
        result[(x, y)] = tile_id
    
    return result


if __name__ == '__main__':
    # Test with a simple rectangle
    import random
    random.seed(42)
    
    positions = set()
    for x in range(7, 14):  # 7 tiles wide
        for y in range(0, 5):  # 5 tiles tall
            positions.add((x, y))
    
    print("Testing 2D style (SMB1):")
    tiles_2d = autotile_ground(positions, 'SMB1')
    for y in range(4, -1, -1):
        row = f"y={y}: "
        for x in range(7, 14):
            row += f"{tiles_2d[(x,y)]:3d}"
        print(row)
    
    print()
    print("Testing 3DW style:")
    tiles_3dw = autotile_ground(positions, '3DW')
    for y in range(4, -1, -1):
        row = f"y={y}: "
        for x in range(7, 14):
            row += f"{tiles_3dw[(x,y)]:3d}"
        print(row)
