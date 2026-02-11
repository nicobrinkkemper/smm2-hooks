#include "smm2/func_trace.h"
#include "smm2/frame.h"
#include "hk/hook/Trampoline.h"

namespace smm2 {
namespace func_trace {

static log::Logger trace_log;

// ============================================================
// Hook transition delegate functions (the 62 checker callbacks)
// These are the functions we're decompiling in PlayerObjectStates.cpp
// Signature: int delegate_callback(PlayerObject* this)
// Return: 0 = don't transition, 1 = transition allowed
//
// For each call we capture:
//   - Input PlayerObject fields before calling original
//   - Return value from original
//   - Output PlayerObject fields after (delegates can modify state)
//
// Host-side test: read CSV, replay with our C++ reimplementation,
// compare return values. Any mismatch = decomp bug.
// ============================================================

// Helper: hook a delegate, capture input/output/return
#define DEFINE_DELEGATE_HOOK(name)                                               \
static HkTrampoline<int, void*> name##_hook =                                   \
    hk::hook::trampoline([](void* player_obj) -> int {                          \
        auto p = reinterpret_cast<uintptr_t>(player_obj);                       \
        PlayerSnapshot input, output;                                            \
        input.capture(p);                                                        \
        int ret = name##_hook.orig(player_obj);                                 \
        output.capture(p);                                                       \
        trace_log.writef("%u," #name ",%d,", frame::current(), ret);            \
        input.write_csv(trace_log);                                              \
        trace_log.write(",", 1);                                                 \
        output.write_csv(trace_log);                                             \
        trace_log.write("\n", 1);                                                \
        return ret;                                                              \
    })

// Start with the functions we've already decompiled
DEFINE_DELEGATE_HOOK(delegate_Walk);
DEFINE_DELEGATE_HOOK(delegate_Crouch);
DEFINE_DELEGATE_HOOK(delegate_CrouchEnd);
DEFINE_DELEGATE_HOOK(delegate_CrouchJump);
DEFINE_DELEGATE_HOOK(delegate_Landing);

void init() {
    trace_log.init("trace.csv");

    // Write header
    trace_log.write("frame,func,return,"
        "in_pos_x,in_pos_y,in_pos_z,in_vel_x,in_vel_y,"
        "in_cur_state,in_state_frames,in_powerup_id,in_facing,"
        "in_target_speed,in_gravity,in_friction,in_accel,"
        "in_in_water,in_style_features,in_game_style_flags,"
        "in_field_490,in_field_484,in_field_488,in_buffered_action,"
        "in_carried_object,in_frame_counter,"
        "out_pos_x,out_pos_y,out_pos_z,out_vel_x,out_vel_y,"
        "out_cur_state,out_state_frames,out_powerup_id,out_facing,"
        "out_target_speed,out_gravity,out_friction,out_accel,"
        "out_in_water,out_style_features,out_game_style_flags,"
        "out_field_490,out_field_484,out_field_488,out_buffered_action,"
        "out_carried_object,out_frame_counter\n", 660);

    // Install hooks via symbols (defined in syms/main.sym)
    delegate_Walk_hook.installAtSym<"delegate_Walk">();
    delegate_Crouch_hook.installAtSym<"delegate_Crouch">();
    delegate_CrouchEnd_hook.installAtSym<"delegate_CrouchEnd">();
    delegate_CrouchJump_hook.installAtSym<"delegate_CrouchJump">();
    delegate_Landing_hook.installAtSym<"delegate_Landing">();
}

void flush() {
    trace_log.flush();
}

} // namespace func_trace
} // namespace smm2
