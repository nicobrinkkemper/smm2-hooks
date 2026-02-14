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
    uint32_t input_poll_count;  // increments when GetNpadStates is called (=play mode)
    int32_t  real_game_phase;   // from GamePhaseManager: 0=title, 2=course maker, 4=story/coursebot
    uint8_t  course_theme;      // 0x3C: 0=Ground,1=Underground,2=Castle,3=Airship,4=Underwater,5=GhostHouse,6=Snow,7=Desert,8=Sky,9=Forest,0xFF=unknown
    uint8_t  _pad2[3];
    uint32_t game_style;        // 0x40: gamestyle from BCD header (0x314d=SMB1,0x334d=SMB3,0x5733=3DW,etc), 0=unknown
};

static_assert(sizeof(StatusBlock) == 68, "StatusBlock size mismatch");

// static_assert to be updated after size is confirmed

void init();
void update(uint32_t frame);
void set_player(uintptr_t player);
void set_mode(uint8_t mode);  // 0=editor, 1=playing

} // namespace status
} // namespace smm2
