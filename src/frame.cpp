#include "smm2/frame.h"
#include "hk/hook/Trampoline.h"

namespace smm2 {
namespace frame {

static uint32_t s_frame = 0;
static callback_t s_cb = nullptr;
static uintptr_t s_scene = 0;

static HkTrampoline<void, void*> procFrame_ =
    hk::hook::trampoline([](void* t) -> void {
        procFrame_.orig(t);
        s_scene = reinterpret_cast<uintptr_t>(t);
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

uintptr_t scene_object() {
    return s_scene;
}

} // namespace frame
} // namespace smm2
