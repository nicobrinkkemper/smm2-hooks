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

// All delegate hooks EXCEPT ≤16B functions (trampoline can't fit)
// Skipped (≤16B): None, Jump, BroadJump, WallClimb, ClimbRollingAttack, WallHitLand, ObjJumpDai
// 47 hooks total, pool size 0x80 (128)
DEFINE_DELEGATE_HOOK(delegate_Walk);
DEFINE_DELEGATE_HOOK(delegate_Landing);
DEFINE_DELEGATE_HOOK(delegate_Crouch);
DEFINE_DELEGATE_HOOK(delegate_CrouchEnd);
DEFINE_DELEGATE_HOOK(delegate_CrouchJump);
DEFINE_DELEGATE_HOOK(delegate_CrouchJumpEnd);
DEFINE_DELEGATE_HOOK(delegate_CrouchSwim);
DEFINE_DELEGATE_HOOK(delegate_CrouchSwimEnd);
DEFINE_DELEGATE_HOOK(delegate_CrouchSwimWalk);
DEFINE_DELEGATE_HOOK(delegate_Rolling);
DEFINE_DELEGATE_HOOK(delegate_BroadJumpLand);
DEFINE_DELEGATE_HOOK(delegate_StartFall);
DEFINE_DELEGATE_HOOK(delegate_WorldShortTurn);
DEFINE_DELEGATE_HOOK(delegate_Turn);
DEFINE_DELEGATE_HOOK(delegate_HipAttack);
DEFINE_DELEGATE_HOOK(delegate_HipAttackEnd);
DEFINE_DELEGATE_HOOK(delegate_Slip);
DEFINE_DELEGATE_HOOK(delegate_RollSlip);
DEFINE_DELEGATE_HOOK(delegate_WallSlide);
DEFINE_DELEGATE_HOOK(delegate_WallJump);
DEFINE_DELEGATE_HOOK(delegate_WallClimbSlide);
DEFINE_DELEGATE_HOOK(delegate_WallClimbFall);
DEFINE_DELEGATE_HOOK(delegate_WallClimbTopJump);
DEFINE_DELEGATE_HOOK(delegate_WallClimbTopCrouchJump);
DEFINE_DELEGATE_HOOK(delegate_ClimbAttack);
DEFINE_DELEGATE_HOOK(delegate_ClimbAttackSwim);
DEFINE_DELEGATE_HOOK(delegate_ClimbJumpAttack);
DEFINE_DELEGATE_HOOK(delegate_ClimbSlidingAttack);
DEFINE_DELEGATE_HOOK(delegate_ClimbBodyAttack);
DEFINE_DELEGATE_HOOK(delegate_ClimbBodyAttackLand);
DEFINE_DELEGATE_HOOK(delegate_WallHit);
DEFINE_DELEGATE_HOOK(delegate_Drag);
DEFINE_DELEGATE_HOOK(delegate_SideJumpDai);
DEFINE_DELEGATE_HOOK(delegate_PlayerJumpDai);
DEFINE_DELEGATE_HOOK(delegate_Swim);
DEFINE_DELEGATE_HOOK(delegate_CrouchSwimJump);
DEFINE_DELEGATE_HOOK(delegate_Fire);
DEFINE_DELEGATE_HOOK(delegate_FireSwim);
DEFINE_DELEGATE_HOOK(delegate_Throw);
DEFINE_DELEGATE_HOOK(delegate_FrogWalk);
DEFINE_DELEGATE_HOOK(delegate_FrogSwim);
DEFINE_DELEGATE_HOOK(delegate_Flying);
DEFINE_DELEGATE_HOOK(delegate_FlyingSlowFall);
DEFINE_DELEGATE_HOOK(delegate_FlyingWallStick);
DEFINE_DELEGATE_HOOK(delegate_LiftUp);
DEFINE_DELEGATE_HOOK(delegate_LiftUpSnowBall);
DEFINE_DELEGATE_HOOK(delegate_LiftUpCloud);
DEFINE_DELEGATE_HOOK(delegate_LiftUpBomb);
DEFINE_DELEGATE_HOOK(delegate_CarryPlayer);

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

    // Install 49 delegate hooks (skipping 7 that are ≤16B)
    delegate_Walk_hook.installAtSym<"delegate_Walk">();
    delegate_Landing_hook.installAtSym<"delegate_Landing">();
    delegate_Crouch_hook.installAtSym<"delegate_Crouch">();
    delegate_CrouchEnd_hook.installAtSym<"delegate_CrouchEnd">();
    delegate_CrouchJump_hook.installAtSym<"delegate_CrouchJump">();
    delegate_CrouchJumpEnd_hook.installAtSym<"delegate_CrouchJumpEnd">();
    delegate_CrouchSwim_hook.installAtSym<"delegate_CrouchSwim">();
    delegate_CrouchSwimEnd_hook.installAtSym<"delegate_CrouchSwimEnd">();
    delegate_CrouchSwimWalk_hook.installAtSym<"delegate_CrouchSwimWalk">();
    delegate_Rolling_hook.installAtSym<"delegate_Rolling">();
    // skip BroadJump (16B)
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
    // skip WallClimb (16B)
    delegate_WallClimbSlide_hook.installAtSym<"delegate_WallClimbSlide">();
    delegate_WallClimbFall_hook.installAtSym<"delegate_WallClimbFall">();
    delegate_WallClimbTopJump_hook.installAtSym<"delegate_WallClimbTopJump">();
    delegate_WallClimbTopCrouchJump_hook.installAtSym<"delegate_WallClimbTopCrouchJump">();
    delegate_ClimbAttack_hook.installAtSym<"delegate_ClimbAttack">();
    delegate_ClimbAttackSwim_hook.installAtSym<"delegate_ClimbAttackSwim">();
    delegate_ClimbJumpAttack_hook.installAtSym<"delegate_ClimbJumpAttack">();
    delegate_ClimbSlidingAttack_hook.installAtSym<"delegate_ClimbSlidingAttack">();
    // skip ClimbRollingAttack (16B)
    delegate_ClimbBodyAttack_hook.installAtSym<"delegate_ClimbBodyAttack">();
    delegate_ClimbBodyAttackLand_hook.installAtSym<"delegate_ClimbBodyAttackLand">();
    delegate_WallHit_hook.installAtSym<"delegate_WallHit">();
    // skip WallHitLand (16B)
    delegate_Drag_hook.installAtSym<"delegate_Drag">();
    // skip ObjJumpDai (16B)
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
