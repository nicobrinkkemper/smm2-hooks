#include <hk/hook/Trampoline.h>
#include <hk/ro/RoUtil.h>
#include "smm2/log.h"
#include "smm2/frame.h"
#include <vector>

namespace smm2 {
namespace rng_trace {

static log::Logger s_log;
static bool s_ready = false;

// Store up to 10 Seed 0 contexts to be safe!
static uintptr_t s_contexts[10] = {0};
static int s_context_count = 0;

static bool is_gameplay_ctx(void* ctx) {
    uintptr_t c = reinterpret_cast<uintptr_t>(ctx);
    for (int i = 0; i < s_context_count; i++) {
        if (s_contexts[i] == c) return true;
    }
    return false;
}

static HkTrampoline<void, void*, uint32_t> rand_init_hook =
    hk::hook::trampoline([](void* ctx, uint32_t seed) -> void {
        if (seed == 0) {
            uintptr_t c = reinterpret_cast<uintptr_t>(ctx);
            if (!is_gameplay_ctx(ctx) && s_context_count < 10) {
                s_contexts[s_context_count++] = c;
            }
        }
        rand_init_hook.orig(ctx, seed);
    });

static HkTrampoline<uint32_t, void*> rand_get32_hook =
    hk::hook::trampoline([](void* ctx) -> uint32_t {
        void* lr = __builtin_return_address(0);
        uintptr_t base = hk::ro::getMainModule()->range().start();
        uintptr_t lr_offset = reinterpret_cast<uintptr_t>(lr) - base;

        if (s_ready && is_gameplay_ctx(ctx)) {
            // Find which index it is
            int idx = 0;
            for (int i = 0; i < s_context_count; i++) {
                if (s_contexts[i] == reinterpret_cast<uintptr_t>(ctx)) {
                    idx = i;
                    break;
                }
            }
            
            uint32_t f = frame::current();
            // Only log after frame 120 to skip boot noise
            if (f > 120) {
                s_log.writef("%u,ctx%d,0x%lx\n", f, idx, lr_offset);  // buffered; main's frame hook flushes
            }
        }
        return rand_get32_hook.orig(ctx);
    });

void flush() {
    s_log.flush();
}

void init() {
    s_log.init("rng_trace.csv");
    s_log.writef("frame,func,lr_offset\n");
    s_log.flush();
    s_ready = true;
    
    rand_init_hook.installAtSym<"Context_init">();
    rand_get32_hook.installAtSym<"Context_getU32">();
}

}} // namespace smm2::rng_trace
