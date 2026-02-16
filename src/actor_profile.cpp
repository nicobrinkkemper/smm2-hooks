/**
 * actor_profile.cpp — Hook actor profile registration to discover behavior indexes
 *
 * Hooks sub_7101047F40 (1143 calls at boot) to log:
 *   - Actor name (sead::SafeStringBase<char>)
 *   - Behavior index (0-18)
 *   - Callback address
 *
 * Also hooks StateMachine::registerState (sub_71008B8FA0) to log:
 *   - State name string
 *   - State ID
 *
 * Output: sd:/smm2-hooks/profiles.csv and sd:/smm2-hooks/actor_states.csv
 *
 * Research: Mario Possamodder (2026-02-16)
 */

#include <hk/hook/Trampoline.h>
#include <hk/ro/RoUtil.h>
#include "smm2/log.h"

namespace smm2 {
namespace actor_profile {

static log::Logger g_profile_log;
static log::Logger g_state_log;
static int g_profile_count = 0;
static int g_state_count = 0;

// sub_7101047F40: registerActorProfile(name, index, callback)
// x0 = sead::SafeStringBase<char>* (stack-constructed: [vtable, char*])
// w1 = behavior index (0-18)
// x2 = callback function pointer
static HkTrampoline<void, void*, unsigned int, void*> profile_hook =
    hk::hook::trampoline([](void* name_obj, unsigned int index, void* callback) -> void {
        const char* name = "unknown";

        // sead::SafeStringBase layout: [8 bytes vtable] [8 bytes char*]
        uintptr_t* ss = (uintptr_t*)name_obj;
        if (ss) {
            const char* str = (const char*)ss[1];
            if (str) {
                name = str;
            }
        }

        if (g_profile_count < 2000) {
            g_profile_log.writef("%s,%u,0x%lx\n", name, index, (unsigned long)callback);
            g_profile_count++;
        }

        profile_hook.orig(name_obj, index, callback);
    });

// sub_71008B8FA0: StateMachine::registerState(sm, state_id, delegate_pair)
// x0 = StateMachine*
// w1 = state_id
// x2 = delegate pair (stack: [vtable, char* state_name])
static HkTrampoline<void, void*, unsigned int, void*> state_hook =
    hk::hook::trampoline([](void* sm, unsigned int state_id, void* delegate_pair) -> void {
        const char* state_name = "unknown";

        // delegate pair: [8 bytes vtable-like pointer] [8 bytes char* name]
        uintptr_t* dp = (uintptr_t*)delegate_pair;
        if (dp) {
            const char* str = (const char*)dp[1];
            if (str) {
                state_name = str;
            }
        }

        if (g_state_count < 20000) {
            g_state_log.writef("%s,%u\n", state_name, state_id);
            g_state_count++;
        }

        state_hook.orig(sm, state_id, delegate_pair);
    });

void init() {
    g_profile_log.init("profiles.csv");
    g_profile_log.write("name,index,callback\n", 20);
    g_state_log.init("actor_states.csv");
    g_state_log.write("state_name,state_id\n", 20);

    profile_hook.installAtSym<"ActorProfileRegister">();
    state_hook.installAtSym<"SMRegisterState">();
}

} // namespace actor_profile
} // namespace smm2
