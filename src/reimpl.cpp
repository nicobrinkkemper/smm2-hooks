#include "smm2/reimpl.h"
#include "smm2/log.h"
#include "smm2/frame.h"
#include "hk/hook/Trampoline.h"
#include "hk/hook/Replace.h"

namespace smm2 {
namespace reimpl {

static log::Logger mismatch_log;

// ============================================================
// VERIFY MODE: Run both original and reimplementation,
// log any mismatches. Game still uses original result.
// This is the safe way to validate before full replacement.
// ============================================================

#define DEFINE_VERIFY_HOOK(name, reimpl_func)                                    \
static HkTrampoline<int, void*> name##_verify =                                 \
    hk::hook::trampoline([](void* player) -> int {                              \
        int orig_ret = name##_verify.orig(player);                              \
        int our_ret = reimpl_func(player);                                      \
        if (orig_ret != our_ret) {                                              \
            auto p = reinterpret_cast<uintptr_t>(player);                       \
            uint32_t state = player::read<uint32_t>(p, player::off::cur_state); \
            uint32_t powerup = player::read<uint32_t>(p, player::off::powerup_id); \
            mismatch_log.writef("%u," #name ",%d,%d,%u,%u\n",                   \
                frame::current(), orig_ret, our_ret, state, powerup);           \
        }                                                                        \
        return orig_ret;  /* always use original in verify mode */              \
    })

// ============================================================
// REPLACE MODE: Fully replace original with our reimplementation.
// Use only after verify mode shows zero mismatches.
// ============================================================

// #define DEFINE_REPLACE(name, reimpl_func)
//     static HkReplace<int, void*> name##_replace(reimpl_func)

// ============================================================
// Reimplemented functions
// ============================================================

// Slot 0: None (sub_71015E4820) — trivial, always returns 0
DEFINE_VERIFY_HOOK(delegate_None, delegate_None);

void init() {
    mismatch_log.init("mismatches.csv");
    mismatch_log.write("frame,func,orig_ret,our_ret,state,powerup\n", 42);

    // Install verify hooks
    delegate_None_verify.installAtSym<"delegate_None">();

    // As more functions are reimplemented, add them here:
    // delegate_Walk_verify.installAtSym<"delegate_Walk">();
    // delegate_Landing_verify.installAtSym<"delegate_Landing">();
    // etc.
}

} // namespace reimpl
} // namespace smm2
