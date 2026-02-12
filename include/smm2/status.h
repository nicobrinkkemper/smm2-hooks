#pragma once

#include <cstdint>

namespace smm2 {
namespace status {

// Game status written to sd:/smm2-hooks/status.bin every frame.
// Host-side tools poll this for instant game state awareness.
//
// Layout (64 bytes):
//   [0x00] uint32_t frame
//   [0x04] uint32_t game_phase     (0=unknown, 4=playing — from GamePhaseManager)
//   [0x08] uint32_t player_state   (from PlayerObject+0x3F8)
//   [0x0C] uint32_t powerup_id     (from PlayerObject+0x4A8)
//   [0x10] float    pos_x
//   [0x14] float    pos_y
//   [0x18] float    vel_x
//   [0x1C] float    vel_y
//   [0x20] uint32_t state_frames   (frames in current state)
//   [0x24] uint8_t  in_water
//   [0x25] uint8_t  is_dead        (1 if state is death-related)
//   [0x26] uint8_t  is_goal        (1 if state is goal-related)
//   [0x27] uint8_t  has_player     (1 if player pointer is valid)
//   [0x28] float    facing         (from +0x26C)
//   [0x2C] float    gravity        (from +0x27C)
//   [0x30] uint32_t buffered_action (from +0x4BC)
//   [0x34] uint32_t _pad[3]

struct StatusBlock {
    uint32_t frame;
    uint32_t game_phase;
    uint32_t player_state;
    uint32_t powerup_id;
    float pos_x;
    float pos_y;
    float vel_x;
    float vel_y;
    uint32_t state_frames;
    uint8_t in_water;
    uint8_t is_dead;
    uint8_t is_goal;
    uint8_t has_player;
    float facing;
    float gravity;
    uint32_t buffered_action;
    uint32_t _pad[3];
};

static_assert(sizeof(StatusBlock) == 64, "StatusBlock must be 64 bytes");

void init();
void update(uint32_t frame);
void set_player(uintptr_t player);
void set_mode(uint8_t mode);  // 0=editor, 1=playing

} // namespace status
} // namespace smm2
