// Course theme override (docs/theme-override.md): sd:/smm2-hooks/theme.txt
// holds a number; every course the game loads gets that main-area theme.
//
// sub_7100E3BA90 copies the course file into the buffer at [obj+0x28]
// ([main+0x2A67B70]+0x28 is that buffer), file header included, so the
// main area's theme byte sits at +0x10 (file header) +0x200 (course
// header) = +0x210. The hook lets the copy run and then writes the byte.
#include "hk/hook/Trampoline.h"
#include "nn/fs.h"

namespace smm2 {
namespace theme_override {

static int s_theme = -1;   // -1: no theme.txt, nothing is hooked

static HkTrampoline<long, long, int, char> course_copy =
    hk::hook::trampoline([](long obj, int a2, char a3) -> long {
        const long ret = course_copy.orig(obj, a2, a3);
        uint8_t* course = *reinterpret_cast<uint8_t**>(obj + 0x28);
        if (course) course[0x210] = static_cast<uint8_t>(s_theme);
        return ret;
    });

void init() {
    nn::fs::FileHandle f;
    if (nn::fs::OpenFile(&f, "sd:/smm2-hooks/theme.txt", nn::fs::MODE_READ) != 0) return;
    char buf[8] = {};
    size_t n = 0;
    nn::fs::ReadFile(&n, f, 0, buf, sizeof(buf) - 1);
    nn::fs::CloseFile(f);
    int v = 0;
    bool digits = false;
    for (size_t i = 0; i < n && buf[i] >= '0' && buf[i] <= '9'; ++i) { v = v * 10 + (buf[i] - '0'); digits = true; }
    if (!digits || v > 255) return;
    s_theme = v;
    course_copy.installAtSym<"CourseDataCopy">();
}

} // namespace theme_override
} // namespace smm2
