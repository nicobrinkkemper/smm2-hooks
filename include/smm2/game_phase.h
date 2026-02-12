#pragma once

#include <cstdint>

namespace smm2 {
namespace game_phase {

// GamePhaseManager global pointer
// Virtual address: 0x7102C57D58
// Structure: gGamePhaseManager->inner(+0x30)->phase(+0x1c)
// From decomp: src/game/actor/ActorBase.h

// Known phase values:
// 4 = playing (in-game, physics active)
// Others TBD — need to capture at title screen, editor, menus, goal animation

// Read the current game phase by following the pointer chain
// Returns -1 if pointer is null
int read_phase();

// Phase constants (confirmed via decomp)
constexpr int PHASE_PLAYING = 4;

void init();

} // namespace game_phase
} // namespace smm2
