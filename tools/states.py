#!/usr/bin/env python3
"""State ID → name lookup from decomp research."""

# From docs/re-notes/confirmed-states.md and player-state-table.md
STATE_NAMES = {
    1: "Walk",
    2: "Fall",
    3: "Jump",
    4: "Landing",
    5: "Crouch",
    6: "CrouchEnd",
    7: "CrouchJump",
    8: "CrouchJumpEnd",
    9: "Damage",
    10: "Death",
    11: "HipAttack",
    12: "HipAttackLand",
    16: "StartFall",  # reset/transition state
    19: "HipAttack_alt",
    21: "WallSlide",
    22: "WallJump",
    25: "Spin",
    27: "SpinJump",
    29: "GroundPound",
    30: "GroundPoundLand",
    33: "Climb",
    34: "ClimbTop",
    39: "SwimMove",  # active swimming with velocity
    40: "SwimFloat",
    43: "SwimIdle",  # also used as editor idle state
    45: "DoorEnter",
    46: "DoorExit",
    47: "PipeEnter",
    48: "PipeExit",
    51: "FlagPoleGrab",
    53: "Spring",
    56: "Carry",
    57: "CarryThrow",
    60: "Slide",
    63: "TurnAround",
    65: "ClimbPole",
    69: "Run",  # sprint
    72: "LongJump",
    77: "CatDive",
    78: "CatClimb",
    80: "PropellerFly",
    83: "AcornGlide",
    89: "SuperJump",
    96: "RaccoonFly",
    97: "RaccoonGlide",
    101: "CapeFloat",
    107: "FrogSwim",
    110: "PBalloonFloat",
    116: "GoalPole",  # goal pole grab animation variant
    122: "GoalPoleGrab",  # initial grab
    124: "GoalBackJump",  # jump off pole into castle
    127: "StarPower",
    130: "MegaMushroom",
    134: "BowserJr",
    140: "Yoshi",
    143: "YoshiDismount",
}

def name(state_id):
    return STATE_NAMES.get(state_id, f"Unknown_{state_id}")

if __name__ == '__main__':
    import sys
    if len(sys.argv) > 1:
        sid = int(sys.argv[1])
        print(f"State {sid} = {name(sid)}")
    else:
        for sid, nm in sorted(STATE_NAMES.items()):
            print(f"  {sid:3d} = {nm}")
