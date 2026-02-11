#pragma once

// Reimplemented delegate functions from PlayerObjectStates.cpp
// These replace the original functions at runtime.
// If the game plays correctly → decomp is verified.
//
// Two modes:
//   REIMPL_VERIFY: run both original + ours, log mismatches (safe)
//   REIMPL_REPLACE: fully replace original (live test)

#include "smm2/player.h"
#include <cstdint>

namespace smm2 {
namespace reimpl {

// Delegate function signature: int callback(PlayerObject* this)
// Returns 0 (don't transition) or 1 (transition allowed)

// Slot 0: None — sub_71015E4820, 8 bytes
// Original: just returns 0
inline int delegate_None(void* player) {
    return 0;
}

// Slot 3: Jump — sub_71015E48A0, 4 bytes
// Original: tail-calls sub_71015E7020
// TODO: implement sub_71015E7020

// Slot 8: CrouchJumpEnd — sub_71015E4B50, 28 bytes
// Original: calls sub_71015C75A0(player, 1) and returns result
// TODO: implement

// Add more as we decompile them from PlayerObjectStates.cpp
// Each function here should be a direct C++ translation of the asm

void init();

} // namespace reimpl
} // namespace smm2
