/**
 * placeholder_debug.cpp — Force spikeball into true placeholder state
 *
 * Based on complete decompilation of EnemyUber + ActorBaseCalc + collision system.
 *
 * The placeholder state works because:
 * 1. ActorBaseCalc checks flags1324: if 0x40000 is NOT set, runs camera bounds check
 * 2. If bounds check fails (offscreen), sets 0x20000
 * 3. At end of ActorBaseCalc, if 0x20000 IS set, collision registration is SKIPPED
 * 4. Without collision registration, no actor can hit the spikeball
 * 5. The spikeball's collision handler (sub_71010F7D80) is never invoked
 * 6. So changeState(Die) is never called
 *
 * The problem with on-screen forcing: ActorBaseCalc sets 0x40000 at LABEL_99
 * and ALSO calls the collision registration (actor[221]->vtable[3]) in the same call.
 * By the time we flip it back, collision is already registered.
 *
 * Solution: Temporarily NULL the collision component pointer (actor+1768 = actor[221])
 * before calling orig(). ActorBaseCalc will see NULL and skip registration.
 * Then restore it after. The actor still has collision data but it won't be
 * registered for hit detection this frame.
 */

#include <hk/hook/Trampoline.h>
#include <hk/ro/RoUtil.h>

namespace smm2 {
namespace placeholder_debug {

// Hook: GabonIronBallWU::calc (sub_71010F2970)
static HkTrampoline<long, void*> ironball_calc_hook =
    hk::hook::trampoline([](void* actor) -> long {
        uintptr_t a = reinterpret_cast<uintptr_t>(actor);
        
        // Save and NULL the collision component pointer at actor+1768
        // This prevents ActorBaseCalc from registering collision
        uintptr_t* collision_ptr = reinterpret_cast<uintptr_t*>(a + 1768);
        uintptr_t saved_collision = *collision_ptr;
        *collision_ptr = 0;
        
        // Run the original calc
        long result = ironball_calc_hook.orig(actor);
        
        // Restore collision component pointer
        *collision_ptr = saved_collision;
        
        // Force placeholder flags (same as what ActorBaseCalc sets for offscreen actors)
        uint32_t* f1324 = reinterpret_cast<uint32_t*>(a + 1324);
        *f1324 = (*f1324 & ~0x40000u) | 0x20000u;
        
        // Set deactivation flags (from LABEL_108 deactivation path)
        uint32_t* f3324 = reinterpret_cast<uint32_t*>(a + 3324);
        *f3324 = (*f3324 & 0xF7FFFFFBu) | 4u;
        
        // Zero velocity so it doesn't drift from its own physics
        float* vel = reinterpret_cast<float*>(a);
        vel[149] = 0.0f;  // velX at +0x254
        vel[150] = 0.0f;  // velY at +0x258
        
        return result;
    });

void init() {
    ironball_calc_hook.installAtSym<"GabonIronBallWU_calc">();
}

}} // namespace smm2::placeholder_debug
