/**
 * placeholder_debug.cpp — Debug: find what's actually moving the spikeball
 *
 * Test: Skip the spikeball's ENTIRE calc. If it still moves,
 * then something outside the calc is responsible.
 * Also log vtable addresses to verify our matching.
 */

#include <hk/hook/Trampoline.h>
#include <hk/ro/RoUtil.h>
#include "smm2/log.h"

namespace smm2 {
namespace placeholder_debug {

static uintptr_t s_base = 0;
static uintptr_t s_vtable_ironball = 0;
static uintptr_t s_vtable_muncher = 0;
static log::Logger s_log;
static int s_log_count = 0;

// Hook 1: GabonIronBallWU::calc (sub_71010F2970)
// DO NOT call original. Just return 1 and log.
static HkTrampoline<long, void*> ironball_calc_hook =
    hk::hook::trampoline([](void* actor) -> long {
        uintptr_t a = reinterpret_cast<uintptr_t>(actor);
        uintptr_t vt = *reinterpret_cast<uintptr_t*>(a);
        
        // Log vtable and position to verify hook is firing
        if (s_log_count < 60) {
            float posX = *reinterpret_cast<float*>(a + 0x230);
            float posY = *reinterpret_cast<float*>(a + 0x234);
            float velX_254 = *reinterpret_cast<float*>(a + 0x254);
            float velX_23C = *reinterpret_cast<float*>(a + 0x23C);
            s_log.writef("calc,vt=0x%lx,expect=0x%lx,posX=%.2f,posY=%.2f,vel254=%.4f,vel23C=%.4f\n",
                vt, s_vtable_ironball, posX, posY, velX_254, velX_23C);
            s_log.flush();
            s_log_count++;
        }
        
        // Set placeholder flag
        uint32_t* f = reinterpret_cast<uint32_t*>(a + 1324);
        *f = (*f & ~0x40000u) | 0x20000u;
        
        // Skip collision
        *reinterpret_cast<uint8_t*>(a + 1326) |= 4;
        
        // DO NOT CALL ORIGINAL — skip everything
        return 1;
    });

// Hook 2: ActorApplyVelocity (sub_71008D7C70)
// Log when called for ANY actor with matching vtable
static HkTrampoline<long, void*> apply_vel_hook =
    hk::hook::trampoline([](void* actor) -> long {
        uintptr_t a = reinterpret_cast<uintptr_t>(actor);
        uintptr_t vt = *reinterpret_cast<uintptr_t*>(a);
        
        if (vt == s_vtable_ironball && s_log_count < 120) {
            float posX = *reinterpret_cast<float*>(a + 0x230);
            float velX = *reinterpret_cast<float*>(a + 0x254);
            s_log.writef("applyvel,vt_match=YES,posX=%.2f,velX=%.4f\n", posX, velX);
            s_log.flush();
            s_log_count++;
            return 1;  // skip
        }
        
        return apply_vel_hook.orig(actor);
    });

void init() {
    s_base = hk::ro::getMainModule()->range().start();
    s_vtable_ironball = s_base + 0x28D1428;
    s_vtable_muncher  = s_base + 0x2913E68;
    
    s_log.init("placeholder_debug.csv");
    s_log.writef("base=0x%lx,vt_ironball=0x%lx,vt_muncher=0x%lx\n",
        s_base, s_vtable_ironball, s_vtable_muncher);
    s_log.flush();

    ironball_calc_hook.installAtSym<"GabonIronBallWU_calc">();
    apply_vel_hook.installAtSym<"ActorApplyVelocity">();
}

}} // namespace smm2::placeholder_debug
