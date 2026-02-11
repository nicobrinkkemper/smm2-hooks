#include "smm2/frame.h"
#include "hk/hook/Trampoline.h"

namespace smm2 {
namespace frame {

static uint32_t s_frame = 0;
static callback_t s_cb = nullptr;

static HkTrampoline<void, void*> procFrame_ =
    hk::hook::trampoline([](void* t) -> void {
        procFrame_.orig(t);
        if (s_cb) s_cb(s_frame);
        s_frame++;
    });

void init(callback_t cb) {
    s_cb = cb;
    procFrame_.installAtSym<"procFrame_">();
}

uint32_t current() {
    return s_frame;
}

} // namespace frame
} // namespace smm2
