/**
 * placeholder_debug.cpp — Force specific enemies into true placeholder state
 *
 * Based on testing feedback:
 *   - Setting flag 0x20000 at +1324 "sort of worked": actor was invisible,
 *     still hit on/off switch (hurt hitbox active), but death animation
 *     still triggered because state machine ran.
 *
 * Strategy: Combine the flag approach with blocking the state elapse.
 *   1. Set 0x20000 at +1324 before calc runs (placeholder rendering + activation)
 *   2. Skip the elapse function entirely (no state machine dispatch, no changeState)
 *   3. Let the base calc still run (collision detection stays active)
 *   4. Zero velocity so position doesn't change
 *
 * This should give: invisible, stationary, can hit on/off, can't die.
 */

#include <hk/hook/Trampoline.h>
#include <hk/ro/RoUtil.h>

namespace smm2 {
namespace placeholder_debug {

static uintptr_t s_base = 0;
static uintptr_t s_vtable_ironball = 0;
static uintptr_t s_vtable_muncher = 0;

static inline bool is_target_actor(uintptr_t actor) {
    if (actor == 0) return false;
    uintptr_t vtable = *reinterpret_cast<uintptr_t*>(actor);
    return (vtable == s_vtable_ironball || vtable == s_vtable_muncher);
}

// Hook 1: GabonIronBallWU::calc (sub_71010F2970)
// Set placeholder flag BEFORE calling original, zero velocity AFTER
static HkTrampoline<long, void*> ironball_calc_hook =
    hk::hook::trampoline([](void* actor) -> long {
        uintptr_t a = reinterpret_cast<uintptr_t>(actor);
        // Set placeholder flag at +1324 (field 331) BEFORE calc
        uint32_t* flags1324 = reinterpret_cast<uint32_t*>(a + 1324);
        *flags1324 = (*flags1324 & ~0x40000u) | 0x20000u;

        long result = ironball_calc_hook.orig(actor);

        // Re-set after calc (in case calc overwrites)
        *flags1324 = (*flags1324 & ~0x40000u) | 0x20000u;
        // Zero velocity so it doesn't drift
        *reinterpret_cast<float*>(a + 0x254) = 0.0f;  // velX
        *reinterpret_cast<float*>(a + 0x258) = 0.0f;  // velY
        return result;
    });

// Hook 2: GabonIronBallWU state elapse (sub_71010F8740)
// Skip entirely — this prevents ALL state changes (death, damage, bounce)
// The elapse is the function that calls changeState and computes movement.
// a1 = component/state object, a1+8 = Actor pointer
static HkTrampoline<void, void*, float> ironball_elapse_hook =
    hk::hook::trampoline([](void* stateObj, float dt) -> void {
        // Read actor ptr from component+8
        uintptr_t actor = *reinterpret_cast<uintptr_t*>(
            reinterpret_cast<uintptr_t>(stateObj) + 8
        );
        // Only skip for target actors
        if (is_target_actor(actor)) {
            return;  // Skip elapse entirely — no state changes, no movement
        }
        ironball_elapse_hook.orig(stateObj, dt);
    });

// Hook 3: EnemyBase shared calc (sub_710111FAB0) — for muncher
// Same approach: set flag before, zero vel after
static HkTrampoline<long, void*> enemy_calc_hook =
    hk::hook::trampoline([](void* actor) -> long {
        uintptr_t a = reinterpret_cast<uintptr_t>(actor);
        uintptr_t vtable = *reinterpret_cast<uintptr_t*>(a);

        if (vtable == s_vtable_muncher) {
            uint32_t* flags1324 = reinterpret_cast<uint32_t*>(a + 1324);
            *flags1324 = (*flags1324 & ~0x40000u) | 0x20000u;

            long result = enemy_calc_hook.orig(actor);

            *flags1324 = (*flags1324 & ~0x40000u) | 0x20000u;
            *reinterpret_cast<float*>(a + 0x254) = 0.0f;
            *reinterpret_cast<float*>(a + 0x258) = 0.0f;
            return result;
        }
        return enemy_calc_hook.orig(actor);
    });

void init() {
    s_base = hk::ro::getMainModule()->range().start();
    s_vtable_ironball = s_base + 0x28D1428;
    s_vtable_muncher  = s_base + 0x2913E68;

    ironball_calc_hook.installAtSym<"GabonIronBallWU_calc">();
    ironball_elapse_hook.installAtSym<"GabonIronBallWU_elapse">();
    enemy_calc_hook.installAtSym<"EnemyBaseCalc">();
}

}} // namespace smm2::placeholder_debug
