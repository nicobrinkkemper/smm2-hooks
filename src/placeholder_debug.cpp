/**
 * placeholder_debug.cpp — Force specific enemies into true dormant/placeholder state
 *
 * Two hooks working together:
 *
 * 1. StateMachine::changeState (sub_71008B9320) — BLOCK all state transitions
 *    for target actors. This prevents death, damage, any behavior change.
 *    The actor stays locked in whatever state it was initialized to.
 *
 * 2. ActorApplyVelocity (sub_71008D7C70) — zero velocity so it doesn't move,
 *    but still call original so the actor stays in the system and renders.
 *
 * Result: actor is visible, stationary, invulnerable, can't die or change state.
 * This is the true "placeholder/dormant" behavior.
 */

#include <hk/hook/Trampoline.h>
#include <hk/ro/RoUtil.h>

namespace smm2 {
namespace placeholder_debug {

static uintptr_t s_base = 0;
static uintptr_t s_vtable_ironball = 0;
static uintptr_t s_vtable_muncher = 0;

static inline bool should_freeze(uintptr_t actor) {
    uintptr_t vtable = *reinterpret_cast<uintptr_t*>(actor);
    return (vtable == s_vtable_ironball || vtable == s_vtable_muncher);
}

// Hook 1: StateMachine::changeState (sub_71008B9320)
// Signature: changeState(StateMachine* sm, int newStateId)
// StateMachine is at actor+0x3F0 (from PlayerObject analysis) or varies.
// The SM is inside the actor. We can get the actor from SM - offset.
// Actually, changeState is called as: sub_71008B9320(a1 + 32, stateId)
// where a1 is the state/component object, and a1+8 = actor pointer.
// So sm = component + 32, and actor = component + 8.
// But since changeState is called from many places, we need the actor.
//
// From the elapse: sub_71008B9320(a1 + 32, 1)
// a1 is the state component, a1+8 = actor ptr.
// sm = a1 + 32, so actor = sm - 32 + 8 = sm - 24
//
// BUT the SM can also be at actor+0x20 (a1+32 where a1=component at actor+X).
// The safest approach: walk back from SM to find the actor by checking vtables.
// 
// Alternative: just check if the SM pointer falls within a frozen actor's memory.
// Actor is 0xD30 bytes for ironball. SM would be at actor + some_offset.
//
// Simpler: the SM is embedded at a fixed offset. From the constructor:
// *(_QWORD *)(v2 + 1256) = v2 + 3360  — controller at +3360
// And changeState is called as sub_71008B9320(a1 + 32, id) where a1 is the
// controller at actor+3360. So SM = actor + 3360 + 32 = actor + 3392.
// Therefore: actor = SM - 3392.
//
// For muncher: same pattern. Constructor has *(_QWORD *)(v2 + 1256) = v2 + 3360.
// So actor = SM - 3392 for both.

static HkTrampoline<void, void*, int> changestate_hook =
    hk::hook::trampoline([](void* sm, int newState) -> void {
        // Try to get actor: SM is at actor + 3360 + 32 = actor + 3392
        uintptr_t sm_addr = reinterpret_cast<uintptr_t>(sm);
        uintptr_t maybe_actor = sm_addr - 3392;
        
        // Validate: check if this looks like an actor with a known vtable
        // Read the first 8 bytes (vtable pointer) and check
        uintptr_t vtable = *reinterpret_cast<uintptr_t*>(maybe_actor);
        if (vtable == s_vtable_ironball || vtable == s_vtable_muncher) {
            // Block the state change — actor stays in current state
            return;
        }
        
        changestate_hook.orig(sm, newState);
    });

// Hook 2: ActorApplyVelocity (sub_71008D7C70)
// Zero velocity for frozen actors so they don't move, but let
// the function run for housekeeping.
static HkTrampoline<long, void*> apply_vel_hook =
    hk::hook::trampoline([](void* actor) -> long {
        if (should_freeze(reinterpret_cast<uintptr_t>(actor))) {
            float* a = reinterpret_cast<float*>(actor);
            a[149] = 0.0f;  // velX at +0x254
            a[150] = 0.0f;  // velY at +0x258
            long result = apply_vel_hook.orig(actor);
            a[149] = 0.0f;
            a[150] = 0.0f;
            return result;
        }
        return apply_vel_hook.orig(actor);
    });

void init() {
    s_base = hk::ro::getMainModule()->range().start();
    s_vtable_ironball = s_base + 0x28D1428;
    s_vtable_muncher  = s_base + 0x2913E68;
    
    changestate_hook.installAtSym<"StateMachine_changeState">();
    apply_vel_hook.installAtSym<"ActorApplyVelocity">();
}

}} // namespace smm2::placeholder_debug
