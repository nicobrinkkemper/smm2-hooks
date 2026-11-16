// Performance mode (docs/perf.md): with sd:/smm2-hooks/perf.txt reading "on",
// the functions MM2Chaos stubs for a simulator on a cheap CPU do nothing:
// drawing, text layout, sound and effect links, the model job queue and the
// course thumbnail. The game logic runs as before on a picture that is no
// longer drawn. Read at boot and again at every scene change.
#include "hk/hook/Trampoline.h"
#include "nn/fs.h"
#include <cstdint>
#include <cstring>

namespace smm2 {
namespace perf {

static bool s_on = false;

// The recursive text layout: reports "not set".
static HkTrampoline<bool, void*, void*, void*> trySetLayoutMsg =
    hk::hook::trampoline([](void* a, void* b, void* c) -> bool {
        return s_on ? false : trySetLayoutMsg.orig(a, b, c);
    });

static HkTrampoline<void, void*, void*> drawRenderStep_ =
    hk::hook::trampoline([](void* a, void* b) -> void {
        if (!s_on) drawRenderStep_.orig(a, b);
    });

static HkTrampoline<void, void*> xlink_calc =
    hk::hook::trampoline([](void* a) -> void {
        if (!s_on) xlink_calc.orig(a);
    });

static HkTrampoline<void, void*, void*, unsigned int, int, int, int> pushBackToJobQueue_ =
    hk::hook::trampoline([](void* a, void* b, unsigned int c, int d, int e, int f) -> void {
        if (!s_on) pushBackToJobQueue_.orig(a, b, c, d, e, f);
    });

static HkTrampoline<void, void*, void*, int> calcLayerDL_ =
    hk::hook::trampoline([](void* a, void* b, int c) -> void {
        if (!s_on) calcLayerDL_.orig(a, b, c);
    });

static HkTrampoline<void, void*, void*, int> calcSubLayerDL_ =
    hk::hook::trampoline([](void* a, void* b, int c) -> void {
        if (!s_on) calcSubLayerDL_.orig(a, b, c);
    });

static HkTrampoline<void, void*> SnapshotTextureMgr_update =
    hk::hook::trampoline([](void* a) -> void {
        if (!s_on) SnapshotTextureMgr_update.orig(a);
    });

static bool wanted() {
    nn::fs::FileHandle f;
    if (nn::fs::OpenFile(&f, "sd:/smm2-hooks/perf.txt", nn::fs::MODE_READ) != 0) return false;
    char buf[8] = {};
    size_t n = 0;
    nn::fs::ReadFile(&n, f, 0, buf, sizeof(buf) - 1);
    nn::fs::CloseFile(f);
    return std::strncmp(buf, "on", 2) == 0;
}

// A function a probe hooked (its first instruction is a branch) is left to the
// probe: a trampoline on top of another would put the wrong instruction back.
static bool hooked(ptr at) {
    return (*reinterpret_cast<const uint32_t*>(at) & 0xFC000000u) == 0x14000000u;
}

#define STUB(fn) if (!hooked(hk::util::lookupSymbol<#fn>())) (void)fn.installAtSym<#fn>()

// Without the flag nothing is hooked: the game's code is untouched.
void reload() {
    const bool on = wanted();
    if (on == s_on) return;
    s_on = on;
    if (on) {
        STUB(trySetLayoutMsg);
        STUB(drawRenderStep_);
        STUB(xlink_calc);
        STUB(pushBackToJobQueue_);
        STUB(calcLayerDL_);
        STUB(calcSubLayerDL_);
        STUB(SnapshotTextureMgr_update);
    } else {
        (void)trySetLayoutMsg.uninstall();
        (void)drawRenderStep_.uninstall();
        (void)xlink_calc.uninstall();
        (void)pushBackToJobQueue_.uninstall();
        (void)calcLayerDL_.uninstall();
        (void)calcSubLayerDL_.uninstall();
        (void)SnapshotTextureMgr_update.uninstall();
    }
}

#undef STUB

} // namespace perf
} // namespace smm2
