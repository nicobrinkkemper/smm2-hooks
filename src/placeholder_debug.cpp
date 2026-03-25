/**
 * placeholder_debug.cpp — Force spikeballs into placeholder (frozen) state
 *
 * Hooks GabonIronBallWU::calc (sub_71010F2970) to force the placeholder flag
 * after the base actor calc runs. This keeps spikeballs stationary but hittable,
 * letting you observe the placeholder mechanic in real-time.
 *
 * Actor flags at +1324:
 *   0x20000 = frozen/placeholder (no movement, no AI)
 *   0x40000 = activated (normal behavior)
 *
 * Toggle: writes to sd:/smm2-hooks/placeholder_on.bin — delete to disable.
 */

#include <hk/hook/Trampoline.h>
#include <hk/ro/RoUtil.h>
#include "smm2/log.h"

namespace smm2 {
namespace placeholder_debug {

static bool s_enabled = true;

// GabonIronBallWU::calc — sub_71010F2970
// a1 = Actor* (the spikeball)
// After this runs, base calc has already set flags1324.
// We override: clear 0x40000 (activated), set 0x20000 (placeholder).
static HkTrampoline<long, void*> ironball_calc_hook =
    hk::hook::trampoline([](void* actor) -> long {
        long result = ironball_calc_hook.orig(actor);

        if (s_enabled) {
            // flags1324 is at actor + 1324 bytes = actor + 0x52C
            uint32_t* flags = reinterpret_cast<uint32_t*>(
                reinterpret_cast<uintptr_t>(actor) + 1324
            );
            *flags = (*flags & ~0x40000u) | 0x20000u;
        }

        return result;
    });

void init() {
    ironball_calc_hook.installAtSym<"GabonIronBallWU_calc">();
}

void toggle(bool enabled) {
    s_enabled = enabled;
}

}} // namespace smm2::placeholder_debug
