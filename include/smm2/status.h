#pragma once

#include <cstdint>

namespace smm2 {
namespace status {

// Game status written to sd:/smm2-hooks/status.bin every frame.
// Host-side tools poll this for instant game state awareness.
//
// Layout (32 bytes):
//   [0x00] uint32_t frame
//   [0x04] uint32_t game_phase     (from GamePhaseManager: 4=playing)
//   [0x08] uint32_t player_state   (from PlayerObject+0x3F8)
//   [0x0C] uint32_t powerup_id     (from PlayerObject+0x4A8)
//   [0x10] float    pos_x
//   [0x14] float    pos_y
//   [0x18] float    vel_x
//   [0x1C] float    vel_y

struct StatusBlock {
    uint32_t frame;
    uint32_t game_phase;
    uint32_t player_state;
    uint32_t powerup_id;
    float pos_x;
    float pos_y;
    float vel_x;
    float vel_y;
};

static_assert(sizeof(StatusBlock) == 32, "StatusBlock must be 32 bytes");

void init();
void update(uint32_t frame);

} // namespace status
} // namespace smm2
