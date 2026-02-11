#pragma once

#include "smm2/log.h"
#include "smm2/player.h"
#include <cstdint>
#include <cstring>

namespace smm2 {
namespace func_trace {

// Captures function input/output pairs for property-based testing.
// For each hooked function call, logs:
//   - Input: relevant PlayerObject fields before the call
//   - Output: return value + modified fields after the call
//
// Host-side test harness reads these vectors and compares against
// our C++ reimplementation.

// Snapshot of PlayerObject fields relevant to state delegates
struct PlayerSnapshot {
    float pos_x, pos_y, pos_z;
    float vel_x, vel_y;
    uint32_t cur_state;
    uint32_t state_frames;
    uint32_t powerup_id;
    uint32_t facing;        // 0x26C
    float target_speed;     // 0x278
    float gravity;          // 0x27C
    float friction;         // 0x280
    float accel;            // 0x284
    uint8_t in_water;       // 0x4C0
    uint8_t style_features; // 0x2308
    uint8_t game_style_flags; // 0x230C
    uint8_t field_490;      // 0x490
    uint32_t field_484;     // 0x484
    uint32_t field_488;     // 0x488
    int32_t buffered_action; // 0x4BC
    uint64_t carried_object; // 0x2718
    uint32_t frame_counter;  // 0x288C

    void capture(uintptr_t p) {
        pos_x       = player::read<float>(p, player::off::pos_x);
        pos_y       = player::read<float>(p, player::off::pos_y);
        pos_z       = player::read<float>(p, 0x238);
        vel_x       = player::read<float>(p, player::off::vel_x);
        vel_y       = player::read<float>(p, player::off::vel_y);
        cur_state   = player::read<uint32_t>(p, player::off::cur_state);
        state_frames = player::read<uint32_t>(p, player::off::state_frames);
        powerup_id  = player::read<uint32_t>(p, player::off::powerup_id);
        facing      = player::read<uint32_t>(p, 0x26C);
        target_speed = player::read<float>(p, 0x278);
        gravity     = player::read<float>(p, 0x27C);
        friction    = player::read<float>(p, 0x280);
        accel       = player::read<float>(p, 0x284);
        in_water    = player::read<uint8_t>(p, player::off::in_water);
        style_features = player::read<uint8_t>(p, 0x2308);
        game_style_flags = player::read<uint8_t>(p, 0x230C);
        field_490   = player::read<uint8_t>(p, 0x490);
        field_484   = player::read<uint32_t>(p, 0x484);
        field_488   = player::read<uint32_t>(p, 0x488);
        buffered_action = player::read<int32_t>(p, 0x4BC);
        carried_object = player::read<uint64_t>(p, 0x2718);
        frame_counter = player::read<uint32_t>(p, 0x288C);
    }

    // Write as binary (fixed size, easy to parse on host)
    void write_bin(uint8_t* out) const {
        std::memcpy(out, this, sizeof(PlayerSnapshot));
    }

    // Write as CSV header
    static void write_csv_header(log::Logger& log) {
        log.write("pos_x,pos_y,pos_z,vel_x,vel_y,cur_state,state_frames,"
                  "powerup_id,facing,target_speed,gravity,friction,accel,"
                  "in_water,style_features,game_style_flags,field_490,"
                  "field_484,field_488,buffered_action,carried_object,frame_counter",
                  222);
    }

    void write_csv(log::Logger& log) const {
        log.writef("%.4f,%.4f,%.4f,%.4f,%.4f,%u,%u,%u,%u,%.4f,%.4f,%.4f,%.4f,"
                   "%u,%u,%u,%u,%u,%u,%d,%llu,%u",
                   pos_x, pos_y, pos_z, vel_x, vel_y, cur_state, state_frames,
                   powerup_id, facing, target_speed, gravity, friction, accel,
                   in_water, style_features, game_style_flags, field_490,
                   field_484, field_488, buffered_action,
                   (unsigned long long)carried_object, frame_counter);
    }
};

// A single test vector: input snapshot + function args + return value + output snapshot
// Written as one CSV row: func_id, frame, args..., input_fields..., return_val, output_fields...

void init();
void flush();

} // namespace func_trace
} // namespace smm2
