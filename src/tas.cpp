#include "smm2/tas.h"
#include "smm2/frame.h"
#include "smm2/log.h"
#include "nn/hid.h"
#include "nn/fs.h"
#include "hk/hook/Trampoline.h"

#include <cstring>
#include <cstdlib>
#include <cstdio>

namespace smm2 {
namespace tas {

// Max 2048 keyframes in a script (should be plenty)
constexpr int MAX_KEYFRAMES = 2048;

struct Keyframe {
    uint32_t frame;
    uint64_t buttons;
    int32_t stick_lx;
    int32_t stick_ly;
};

static Keyframe script[MAX_KEYFRAMES];
static int script_len = 0;
static int script_idx = 0;  // current position in script
static bool active = false;

// Current injected state
static uint64_t cur_buttons = 0;
static int32_t cur_lx = 0;
static int32_t cur_ly = 0;

// Parse script from SD card
static bool load_script() {
    nn::fs::FileHandle f;
    if (nn::fs::OpenFile(&f, "sd:/smm2-hooks/tas.csv", nn::fs::MODE_READ) != 0)
        return false;

    // Read entire file (max 64KB)
    char buf[65536];
    size_t bytes_read = 0;
    nn::fs::ReadFile(&bytes_read, f, 0, buf, sizeof(buf) - 1);
    nn::fs::CloseFile(f);
    buf[bytes_read] = '\0';

    // Parse CSV lines
    script_len = 0;
    char* line = buf;

    // Skip header
    char* nl = std::strchr(line, '\n');
    if (nl) line = nl + 1;

    while (*line && script_len < MAX_KEYFRAMES) {
        Keyframe& kf = script[script_len];

        // Parse: frame,buttons,stick_lx,stick_ly
        kf.frame = (uint32_t)std::strtoul(line, &line, 10);
        if (*line == ',') line++;

        // buttons can be hex (0x...) or decimal
        kf.buttons = (uint64_t)std::strtoull(line, &line, 0);
        if (*line == ',') line++;

        kf.stick_lx = (int32_t)std::strtol(line, &line, 10);
        if (*line == ',') line++;

        kf.stick_ly = (int32_t)std::strtol(line, &line, 10);

        // Skip to next line
        while (*line && *line != '\n') line++;
        if (*line == '\n') line++;

        script_len++;
    }

    return script_len > 0;
}

// Hook nn::hid::GetNpadStates — intercept controller input
static HkTrampoline<int, nn::hid::full_key_state*, int, const uint32_t&> npad_hook =
    hk::hook::trampoline([](nn::hid::full_key_state* out, int count, const uint32_t& id) -> int {
        int written = npad_hook.orig(out, count, id);

        if (!active || script_len == 0) return written;

        uint32_t f = frame::current();

        // Advance script to current frame
        while (script_idx < script_len && script[script_idx].frame <= f) {
            cur_buttons = script[script_idx].buttons;
            cur_lx = script[script_idx].stick_lx;
            cur_ly = script[script_idx].stick_ly;
            script_idx++;
        }

        // Override input for all returned states
        for (int i = 0; i < written; i++) {
            out[i].buttons = cur_buttons;
            out[i].sl_x = cur_lx;
            out[i].sl_y = cur_ly;
        }

        // Script finished?
        if (script_idx >= script_len && cur_buttons == 0) {
            active = false;
        }

        return written;
    });

void init() {
    if (load_script()) {
        active = true;
        script_idx = 0;
        cur_buttons = 0;
        cur_lx = 0;
        cur_ly = 0;

        npad_hook.installAtSym<"_ZN2nn3hid13GetNpadStatesEPNS0_16NpadFullKeyStateEiRKj">();
    }
    // If no tas.csv exists, TAS is simply not active — normal gameplay
}

} // namespace tas
} // namespace smm2
