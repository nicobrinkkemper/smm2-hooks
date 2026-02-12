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

// All direct-address delegate hooks (slots 0-58, skipping vtable redirects)
DEFINE_DELEGATE_HOOK(delegate_None);           // slot 0
DEFINE_DELEGATE_HOOK(delegate_Walk);           // slot 1
// slot 2 (Fall) = vtable redirect, can't hook directly
DEFINE_DELEGATE_HOOK(delegate_Jump);           // slot 3
DEFINE_DELEGATE_HOOK(delegate_Landing);        // slot 4
DEFINE_DELEGATE_HOOK(delegate_Crouch);         // slot 5
DEFINE_DELEGATE_HOOK(delegate_CrouchEnd);      // slot 6
DEFINE_DELEGATE_HOOK(delegate_CrouchJump);     // slot 7
DEFINE_DELEGATE_HOOK(delegate_CrouchJumpEnd);  // slot 8
DEFINE_DELEGATE_HOOK(delegate_CrouchSwim);     // slot 9
DEFINE_DELEGATE_HOOK(delegate_CrouchSwimEnd);  // slot 10
// slot 11 (CrouchWalk) = vtable redirect
DEFINE_DELEGATE_HOOK(delegate_CrouchSwimWalk); // slot 12
DEFINE_DELEGATE_HOOK(delegate_Rolling);        // slot 13
DEFINE_DELEGATE_HOOK(delegate_BroadJump);      // slot 14
DEFINE_DELEGATE_HOOK(delegate_BroadJumpLand);  // slot 15
DEFINE_DELEGATE_HOOK(delegate_StartFall);      // slot 16
DEFINE_DELEGATE_HOOK(delegate_WorldShortTurn); // slot 17
DEFINE_DELEGATE_HOOK(delegate_Turn);           // slot 18
DEFINE_DELEGATE_HOOK(delegate_HipAttack);      // slot 19
DEFINE_DELEGATE_HOOK(delegate_HipAttackEnd);   // slot 20
DEFINE_DELEGATE_HOOK(delegate_Slip);           // slot 21
DEFINE_DELEGATE_HOOK(delegate_RollSlip);       // slot 22
DEFINE_DELEGATE_HOOK(delegate_WallSlide);      // slot 23
DEFINE_DELEGATE_HOOK(delegate_WallJump);       // slot 24
DEFINE_DELEGATE_HOOK(delegate_WallClimb);      // slot 25
DEFINE_DELEGATE_HOOK(delegate_WallClimbSlide); // slot 26
DEFINE_DELEGATE_HOOK(delegate_WallClimbFall);  // slot 27
DEFINE_DELEGATE_HOOK(delegate_WallClimbTopJump); // slot 28
DEFINE_DELEGATE_HOOK(delegate_WallClimbTopCrouchJump); // slot 29
DEFINE_DELEGATE_HOOK(delegate_ClimbAttack);    // slot 30
DEFINE_DELEGATE_HOOK(delegate_ClimbAttackSwim); // slot 31
DEFINE_DELEGATE_HOOK(delegate_ClimbJumpAttack); // slot 32
DEFINE_DELEGATE_HOOK(delegate_ClimbSlidingAttack); // slot 33
DEFINE_DELEGATE_HOOK(delegate_ClimbRollingAttack); // slot 34
DEFINE_DELEGATE_HOOK(delegate_ClimbBodyAttack); // slot 35
DEFINE_DELEGATE_HOOK(delegate_ClimbBodyAttackLand); // slot 36
DEFINE_DELEGATE_HOOK(delegate_WallHit);        // slot 37
DEFINE_DELEGATE_HOOK(delegate_WallHitLand);    // slot 38
DEFINE_DELEGATE_HOOK(delegate_Drag);           // slot 39
DEFINE_DELEGATE_HOOK(delegate_ObjJumpDai);     // slot 40
DEFINE_DELEGATE_HOOK(delegate_SideJumpDai);    // slot 41
DEFINE_DELEGATE_HOOK(delegate_PlayerJumpDai);  // slot 42
DEFINE_DELEGATE_HOOK(delegate_Swim);           // slot 43
DEFINE_DELEGATE_HOOK(delegate_CrouchSwimJump); // slot 44
DEFINE_DELEGATE_HOOK(delegate_Fire);           // slot 45
DEFINE_DELEGATE_HOOK(delegate_FireSwim);       // slot 46
DEFINE_DELEGATE_HOOK(delegate_Throw);          // slot 47
DEFINE_DELEGATE_HOOK(delegate_FrogWalk);       // slot 48
DEFINE_DELEGATE_HOOK(delegate_FrogSwim);       // slot 49
// slot 50 (BalloonFloat) = not registered
DEFINE_DELEGATE_HOOK(delegate_Flying);         // slot 51
DEFINE_DELEGATE_HOOK(delegate_FlyingSlowFall); // slot 52
DEFINE_DELEGATE_HOOK(delegate_FlyingWallStick); // slot 53
DEFINE_DELEGATE_HOOK(delegate_LiftUp);         // slot 54
DEFINE_DELEGATE_HOOK(delegate_LiftUpSnowBall); // slot 55
DEFINE_DELEGATE_HOOK(delegate_LiftUpCloud);    // slot 56
DEFINE_DELEGATE_HOOK(delegate_LiftUpBomb);     // slot 57
DEFINE_DELEGATE_HOOK(delegate_CarryPlayer);    // slot 58

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

    // Install all delegate hooks
    delegate_None_hook.installAtSym<"delegate_None">();
    delegate_Walk_hook.installAtSym<"delegate_Walk">();
    delegate_Jump_hook.installAtSym<"delegate_Jump">();
    delegate_Landing_hook.installAtSym<"delegate_Landing">();
    delegate_Crouch_hook.installAtSym<"delegate_Crouch">();
    delegate_CrouchEnd_hook.installAtSym<"delegate_CrouchEnd">();
    delegate_CrouchJump_hook.installAtSym<"delegate_CrouchJump">();
    delegate_CrouchJumpEnd_hook.installAtSym<"delegate_CrouchJumpEnd">();
    delegate_CrouchSwim_hook.installAtSym<"delegate_CrouchSwim">();
    delegate_CrouchSwimEnd_hook.installAtSym<"delegate_CrouchSwimEnd">();
    delegate_CrouchSwimWalk_hook.installAtSym<"delegate_CrouchSwimWalk">();
    delegate_Rolling_hook.installAtSym<"delegate_Rolling">();
    delegate_BroadJump_hook.installAtSym<"delegate_BroadJump">();
    delegate_BroadJumpLand_hook.installAtSym<"delegate_BroadJumpLand">();
    delegate_StartFall_hook.installAtSym<"delegate_StartFall">();
    delegate_WorldShortTurn_hook.installAtSym<"delegate_WorldShortTurn">();
    delegate_Turn_hook.installAtSym<"delegate_Turn">();
    delegate_HipAttack_hook.installAtSym<"delegate_HipAttack">();
    delegate_HipAttackEnd_hook.installAtSym<"delegate_HipAttackEnd">();
    delegate_Slip_hook.installAtSym<"delegate_Slip">();
    delegate_RollSlip_hook.installAtSym<"delegate_RollSlip">();
    delegate_WallSlide_hook.installAtSym<"delegate_WallSlide">();
    delegate_WallJump_hook.installAtSym<"delegate_WallJump">();
    delegate_WallClimb_hook.installAtSym<"delegate_WallClimb">();
    delegate_WallClimbSlide_hook.installAtSym<"delegate_WallClimbSlide">();
    delegate_WallClimbFall_hook.installAtSym<"delegate_WallClimbFall">();
    delegate_WallClimbTopJump_hook.installAtSym<"delegate_WallClimbTopJump">();
    delegate_WallClimbTopCrouchJump_hook.installAtSym<"delegate_WallClimbTopCrouchJump">();
    delegate_ClimbAttack_hook.installAtSym<"delegate_ClimbAttack">();
    delegate_ClimbAttackSwim_hook.installAtSym<"delegate_ClimbAttackSwim">();
    delegate_ClimbJumpAttack_hook.installAtSym<"delegate_ClimbJumpAttack">();
    delegate_ClimbSlidingAttack_hook.installAtSym<"delegate_ClimbSlidingAttack">();
    delegate_ClimbRollingAttack_hook.installAtSym<"delegate_ClimbRollingAttack">();
    delegate_ClimbBodyAttack_hook.installAtSym<"delegate_ClimbBodyAttack">();
    delegate_ClimbBodyAttackLand_hook.installAtSym<"delegate_ClimbBodyAttackLand">();
    delegate_WallHit_hook.installAtSym<"delegate_WallHit">();
    delegate_WallHitLand_hook.installAtSym<"delegate_WallHitLand">();
    delegate_Drag_hook.installAtSym<"delegate_Drag">();
    delegate_ObjJumpDai_hook.installAtSym<"delegate_ObjJumpDai">();
    delegate_SideJumpDai_hook.installAtSym<"delegate_SideJumpDai">();
    delegate_PlayerJumpDai_hook.installAtSym<"delegate_PlayerJumpDai">();
    delegate_Swim_hook.installAtSym<"delegate_Swim">();
    delegate_CrouchSwimJump_hook.installAtSym<"delegate_CrouchSwimJump">();
    delegate_Fire_hook.installAtSym<"delegate_Fire">();
    delegate_FireSwim_hook.installAtSym<"delegate_FireSwim">();
    delegate_Throw_hook.installAtSym<"delegate_Throw">();
    delegate_FrogWalk_hook.installAtSym<"delegate_FrogWalk">();
    delegate_FrogSwim_hook.installAtSym<"delegate_FrogSwim">();
    delegate_Flying_hook.installAtSym<"delegate_Flying">();
    delegate_FlyingSlowFall_hook.installAtSym<"delegate_FlyingSlowFall">();
    delegate_FlyingWallStick_hook.installAtSym<"delegate_FlyingWallStick">();
    delegate_LiftUp_hook.installAtSym<"delegate_LiftUp">();
    delegate_LiftUpSnowBall_hook.installAtSym<"delegate_LiftUpSnowBall">();
    delegate_LiftUpCloud_hook.installAtSym<"delegate_LiftUpCloud">();
    delegate_LiftUpBomb_hook.installAtSym<"delegate_LiftUpBomb">();
    delegate_CarryPlayer_hook.installAtSym<"delegate_CarryPlayer">();
}

void flush() {
    trace_log.flush();
}

} // namespace func_trace
} // namespace smm2
