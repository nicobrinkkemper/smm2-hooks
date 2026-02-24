/**
 * Sim trace capture — logs player state + input every frame for sim comparison.
 * 
 * Output: sd:/smm2-hooks/sim_trace.csv
 * Format: frame,pos_x,pos_y,vel_x,vel_y,state,state_frames,powerup,on_ground,gravity,buttons
 * 
 * This captures everything needed to:
 * 1. Replay inputs through the WASM sim
 * 2. Compare sim output against real game output frame-by-frame
 * 
 * Enable by creating sd:/smm2-hooks/sim_trace_enabled
 * Disable by removing that file (or restarting without it)
 */

#include "smm2/log.h"
#include "smm2/player.h"
#include "smm2/frame.h"
#include "smm2/game_phase.h"
#include "smm2/status.h"
#include "smm2/tas.h"

#include <nn/fs.h>

namespace smm2 {
namespace sim_trace {

static log::Logger trace_log;
static bool enabled = false;
static bool initialized = false;
static uint32_t capture_start_frame = 0;

// Read current input buttons from nn::hid state
// (TAS module hooks this, so we get either real or scripted input)
static uint64_t read_buttons() {
    // Access the nn::hid shared memory for controller state
    // For now, use the TAS poll count as a proxy — 
    // TODO: hook nn::hid::GetNpadState directly to capture buttons
    return 0;  // Placeholder until we wire up input capture
}

void init() {
    // Check if trace capture is enabled
    nn::fs::DirectoryEntryType type;
    nn::Result rc = nn::fs::GetEntryType(&type, "sd:/smm2-hooks/sim_trace_enabled");
    if (rc.IsSuccess()) {
        enabled = true;
        trace_log.init("sim_trace.csv");
        trace_log.write(
            "frame,pos_x,pos_y,vel_x,vel_y,state,state_frames,powerup,gravity,terminal_vel\n",
            82);
        initialized = true;
    }
}

void per_frame(uint32_t frame) {
    if (!enabled || !initialized) return;
    
    // Only capture during gameplay (phase 3=editor/play, 4=coursebot)
    int phase = smm2::game_phase::read_phase();
    if (phase != 3 && phase != 4) return;
    
    uintptr_t player = status::get_player();
    if (player == 0) return;
    
    // Read all player fields
    float pos_x = player::read<float>(player, player::off::pos_x);
    float pos_y = player::read<float>(player, player::off::pos_y);
    float vel_x = player::read<float>(player, player::off::vel_x);
    float vel_y = player::read<float>(player, player::off::vel_y);
    uint32_t state = player::read<uint32_t>(player, player::off::cur_state);
    uint32_t state_frames = player::read<uint32_t>(player, player::off::state_frames);
    uint32_t powerup = player::read<uint32_t>(player, player::off::powerup_id);
    
    // Read gravity and terminal velocity from player struct
    float gravity = player::read<float>(player, 0x280);
    float terminal_vel = player::read<float>(player, 0x27C);
    
    trace_log.writef("%u,%.4f,%.4f,%.4f,%.4f,%u,%u,%u,%.6f,%.4f\n",
        frame, pos_x, pos_y, vel_x, vel_y,
        state, state_frames, powerup,
        gravity, terminal_vel);
    
    // Flush every 5 seconds (300 frames at 60fps)
    if (frame % 300 == 0) {
        trace_log.flush();
    }
}

void flush() {
    if (initialized) {
        trace_log.flush();
    }
}

} // namespace sim_trace
} // namespace smm2
