#include "smm2/log.h"
#include "smm2/player.h"
#include "smm2/frame.h"
#include "hk/hook/Trampoline.h"
#include "hk/ro/RoUtil.h"

namespace smm2 {
namespace state_logger {

static log::Logger logger;

// Hook StateMachine::changeState
// Signature: void changeState(StateMachine* this, u32 stateID)
// x0 = this (StateMachine), w1 = new state ID
static HkTrampoline<void, void*, uint32_t> changeState_hook =
    hk::hook::trampoline([](void* sm, uint32_t new_state) -> void {
        // Read old state before it gets overwritten (StateMachine+0x08)
        uint32_t old_state = *reinterpret_cast<uint32_t*>(
            reinterpret_cast<uintptr_t>(sm) + 0x08);

        // Call original
        changeState_hook.orig(sm, new_state);

        // Log: frame,old_state,new_state,sm_ptr
        logger.writef("%u,%u,%u,%p\n",
            frame::current(), old_state, new_state, sm);
    });

void init() {
    logger.init("states.csv");
    logger.write("frame,old_state,new_state,sm_ptr\n", 34);
    changeState_hook.installAtSym<"StateMachine_changeState">();
}

void flush() {
    logger.flush();
}

} // namespace state_logger
} // namespace smm2
