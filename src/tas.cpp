#include "smm2/tas.h"
#include "smm2/frame.h"
#include "smm2/status.h"
#include "smm2/log.h"
#include "nn/hid.h"
#include "nn/fs.h"
#include "hk/hook/Trampoline.h"

#include <cstring>
#include <cstdlib>
#include <cstdio>

namespace smm2 {
namespace tas {

// ============================================================
// Two modes of input injection:
//
// 1. SCRIPT MODE: reads tas.csv at boot, plays back keyframes
//    Good for reproducible test sequences.
//
// 2. LIVE MODE: polls sd:/smm2-hooks/input.bin every frame
//    8 bytes: buttons(u64). Written by host, read by hook.
//    Good for real-time remote control from WSL.
//
// If tas.csv exists → script mode. Otherwise → live mode.
// ============================================================

// --- Script mode ---
constexpr int MAX_KEYFRAMES = 2048;

struct Keyframe {
    uint32_t frame;
    uint64_t buttons;
    int32_t stick_lx;
    int32_t stick_ly;
};

static Keyframe script[MAX_KEYFRAMES];
static int script_len = 0;
static int script_idx = 0;
static bool script_active = false;

static bool load_script() {
    nn::fs::FileHandle f;
    if (nn::fs::OpenFile(&f, "sd:/smm2-hooks/tas.csv", nn::fs::MODE_READ) != 0)
        return false;

    char buf[65536];
    size_t bytes_read = 0;
    nn::fs::ReadFile(&bytes_read, f, 0, buf, sizeof(buf) - 1);
    nn::fs::CloseFile(f);
    buf[bytes_read] = '\0';

    script_len = 0;
    char* line = buf;

    // Skip header
    char* nl = std::strchr(line, '\n');
    if (nl) line = nl + 1;

    while (*line && script_len < MAX_KEYFRAMES) {
        Keyframe& kf = script[script_len];
        kf.frame = (uint32_t)std::strtoul(line, &line, 10);
        if (*line == ',') line++;
        kf.buttons = (uint64_t)std::strtoull(line, &line, 0);
        if (*line == ',') line++;
        kf.stick_lx = (int32_t)std::strtol(line, &line, 10);
        if (*line == ',') line++;
        kf.stick_ly = (int32_t)std::strtol(line, &line, 10);
        while (*line && *line != '\n') line++;
        if (*line == '\n') line++;
        script_len++;
    }

    return script_len > 0;
}

// --- Live mode ---
struct LiveInput {
    uint64_t buttons;
    int32_t stick_lx;
    int32_t stick_ly;
};

static bool live_mode = false;

static bool read_live_input(LiveInput& out) {
    nn::fs::FileHandle f;
    if (nn::fs::OpenFile(&f, "sd:/smm2-hooks/input.bin", nn::fs::MODE_READ) != 0)
        return false;

    uint8_t buf[16];
    size_t bytes_read = 0;
    nn::fs::ReadFile(&bytes_read, f, 0, buf, sizeof(buf));
    nn::fs::CloseFile(f);

    if (bytes_read >= 8) {
        std::memcpy(&out.buttons, buf, 8);
        if (bytes_read >= 16) {
            std::memcpy(&out.stick_lx, buf + 8, 4);
            std::memcpy(&out.stick_ly, buf + 12, 4);
        } else {
            out.stick_lx = 0;
            out.stick_ly = 0;
        }
        return true;
    }
    return false;
}

// --- Shared state ---
static uint64_t cur_buttons = 0;
static int32_t cur_lx = 0;
static int32_t cur_ly = 0;
static uint32_t s_input_poll_count = 0;  // increments each GetNpadStates call

// Common input update logic (called from any NpadStates variant hook)
static void update_input() {
    s_input_poll_count++;
    // Fallback status update — fires in ALL scenes (editor, menu, loading)
    status::update_from_input_poll();

    // Script mode: advance keyframes
    if (script_active && script_len > 0) {
        uint32_t f = frame::current();
        while (script_idx < script_len && script[script_idx].frame <= f) {
            cur_buttons = script[script_idx].buttons;
            cur_lx = script[script_idx].stick_lx;
            cur_ly = script[script_idx].stick_ly;
            script_idx++;
        }
        if (script_idx >= script_len && cur_buttons == 0) {
            script_active = false;
        }
    }

    // Live mode: read input file every 2 frames
    if (live_mode && (frame::current() % 2 == 0)) {
        LiveInput inp;
        if (read_live_input(inp)) {
            cur_buttons = inp.buttons;
            cur_lx = inp.stick_lx;
            cur_ly = inp.stick_ly;
        }
    }
}

static void inject_buttons(nn::hid::full_key_state* out, int written) {
    for (int i = 0; i < written; i++) {
        out[i].buttons |= cur_buttons;
        if (cur_lx != 0) out[i].sl_x = cur_lx;
        if (cur_ly != 0) out[i].sl_y = cur_ly;
    }
}

// Hook GetNpadStates(NpadFullKeyState*) — Pro Controller
static HkTrampoline<int, nn::hid::full_key_state*, int, const uint32_t&> npad_fullkey_hook =
    hk::hook::trampoline([](nn::hid::full_key_state* out, int count, const uint32_t& id) -> int {
        int written = npad_fullkey_hook.orig(out, count, id);
        update_input();
        inject_buttons(out, written);
        return written;
    });

uint32_t input_poll_count() {
    return s_input_poll_count;
}

void init() {
    if (load_script()) {
        script_active = true;
        script_idx = 0;
    } else {
        // No script → try live mode
        // Create input.bin if it doesn't exist
        nn::fs::CreateFile("sd:/smm2-hooks/input.bin", 16);
        live_mode = true;
    }

    npad_fullkey_hook.installAtSym<"_ZN2nn3hid13GetNpadStatesEPNS0_16NpadFullKeyStateEiRKj">();
}

} // namespace tas
} // namespace smm2
