/**
 * placeholder_debug.cpp — Dump actor collision sizes at runtime
 *
 * Hooks EnemyUber::execute (sub_7101286EE0) to log the collision dimensions
 * for every enemy actor each frame. Outputs to sd:/smm2-hooks/actor_sizes.csv
 *
 * Fields dumped per actor:
 *   - vtable address (identifies the actor class)
 *   - getClassName result (actual name string)
 *   - posX, posY
 *   - sizeX (+0x28C), sizeY (+0x290)
 *   - offsetX (+0x2F8), offsetY (+0x2FC)
 *   - scaleX (+0x18)
 *   - flags88 (big variant etc)
 *   - collision size at +660/+664 (if different from sizeX/Y)
 */

#include <hk/hook/Trampoline.h>
#include <hk/ro/RoUtil.h>
#include "smm2/log.h"
#include "smm2/frame.h"

namespace smm2 {
namespace placeholder_debug {

static log::Logger s_log;
static bool s_ready = false;
static int s_dump_count = 0;

// Hook Actor::execute (sub_71008D79D0) — called for every active actor
// This is the top-level per-frame entry point
static HkTrampoline<long, void*> actor_execute_hook =
    hk::hook::trampoline([](void* actor) -> long {
        long result = actor_execute_hook.orig(actor);
        
        if (!s_ready || s_dump_count > 5000)
            return result;
        
        uint32_t frame = frame::current();
        // Only dump on frame 120 (about 2 seconds in — actors are loaded)
        if (frame != 120 && frame != 121)
            return result;
        
        uintptr_t a = reinterpret_cast<uintptr_t>(actor);
        uintptr_t base = hk::ro::getMainModule()->range().start();
        
        // Get vtable
        uintptr_t vtable = *reinterpret_cast<uintptr_t*>(a);
        uintptr_t vt_offset = vtable - base;
        
        // Call getClassName (vtable slot 2, offset +16)
        typedef const char* (*GetClassNameFn)(void*);
        GetClassNameFn getClassName = reinterpret_cast<GetClassNameFn>(
            *reinterpret_cast<uintptr_t*>(vtable + 16)
        );
        const char* name = getClassName(actor);
        if (!name) name = "null";
        
        // Read fields
        float posX = *reinterpret_cast<float*>(a + 0x230);
        float posY = *reinterpret_cast<float*>(a + 0x234);
        float sizeX = *reinterpret_cast<float*>(a + 0x28C);
        float sizeY = *reinterpret_cast<float*>(a + 0x290);
        float offsetX = *reinterpret_cast<float*>(a + 0x2F8);
        float offsetY = *reinterpret_cast<float*>(a + 0x2FC);
        float scaleX = *reinterpret_cast<float*>(a + 0x18);
        uint32_t flags88 = *reinterpret_cast<uint32_t*>(a + 88);
        
        // Collision box at +660/+664 (alternative sizes used by some actors)
        float col660 = *reinterpret_cast<float*>(a + 660);
        float col664 = *reinterpret_cast<float*>(a + 664);
        
        s_log.writef("%u,%s,vt=0x%x,px=%.1f,py=%.1f,sx=%.1f,sy=%.1f,ox=%.1f,oy=%.1f,sc=%.2f,f88=0x%x,c660=%.1f,c664=%.1f\n",
            frame, name, (unsigned)vt_offset,
            posX, posY, sizeX, sizeY, offsetX, offsetY, scaleX,
            flags88, col660, col664);
        s_dump_count++;
        
        if (s_dump_count % 50 == 0)
            s_log.flush();
        
        return result;
    });

void init() {
    s_log.init("actor_sizes.csv");
    s_log.writef("frame,name,vtable,posX,posY,sizeX,sizeY,offsetX,offsetY,scale,flags88,col660,col664\n");
    s_log.flush();
    s_ready = true;
    
    actor_execute_hook.installAtSym<"ActorExecute">();
}

}} // namespace smm2::placeholder_debug
