#pragma once

#include <cstdint>

namespace smm2 {
namespace player {

// Known PlayerObject field offsets (v3.0.3)
// All relative to PlayerObject base (this)
namespace off {
    constexpr uint32_t pos_x       = 0x230;  // float (GDB-confirmed: 1220.25 in-level)
    constexpr uint32_t pos_y       = 0x234;  // float (GDB-confirmed: 64 in-level)
    constexpr uint32_t pos_z       = 0x238;  // float
    constexpr uint32_t vel_y       = 0x240;  // float
    constexpr uint32_t vel_x       = 0x274;  // float
    constexpr uint32_t state_machine = 0x3F0; // StateMachine*
    constexpr uint32_t cur_state   = 0x3F8;  // u32 (StateMachine+0x08)
    constexpr uint32_t state_frames = 0x3FC; // u32 (StateMachine+0x0C) — frames in current state
    constexpr uint32_t powerup_id = 0x4A8;     // u32 — powerup/suit enum (0=Small..15=SMB2Mushroom, 8=unused)
    constexpr uint32_t in_water    = 0x4C0;  // bool
    constexpr uint32_t style_features = 0x2308; // u32
}

// State IDs (from Possamodder's enum, GDB-confirmed subset)
namespace state {
    constexpr uint32_t None         = 0;
    constexpr uint32_t Walk         = 1;
    constexpr uint32_t Fall         = 2;
    constexpr uint32_t Jump         = 3;
    constexpr uint32_t Landing      = 4;
    constexpr uint32_t Crouch       = 5;
    constexpr uint32_t CrouchEnd    = 6;
    constexpr uint32_t CrouchJump   = 7;
    constexpr uint32_t StartFall    = 16;
    constexpr uint32_t Turn         = 18;
    constexpr uint32_t WallJump     = 24;
    constexpr uint32_t TailFlying   = 73;
    constexpr uint32_t TailSlowFall = 74;
    constexpr uint32_t TailAttack   = 75;
    constexpr uint32_t GoalPole     = 122;
    constexpr uint32_t GoalBackJump = 124;
}

// Read a field from PlayerObject at runtime
template<typename T>
inline T read(uintptr_t player_base, uint32_t offset) {
    return *reinterpret_cast<T*>(player_base + offset);
}

} // namespace player
} // namespace smm2
