// Direct boot: skip the title and the Coursebot menus by asking the game for
// the course scene the way the Coursebot's Play button does.
//
// sd:/smm2-hooks/boot.txt, read once at boot:
//     coursebot <index> [kind] play the Coursebot entry <index> as soon as the title is up;
//                              kind is the transition (4 = cMyCourseToNormalPlay, 3 = cRoboToEdit)
//
// The Coursebot's play-start (sub_71016E5C10) is four calls, replayed here:
//     sub_7101792070(kind, params)       prepare the transition
//     sub_7101790480(kind)               game mode
//     sub_7101792890(kind, index, params) course source: Coursebot entry
//     sub_7101791020(nullptr)            default play parameters, then the scene request
// which ends in SceneMgr::requestChangeScene(mgr, 4, 0, 1) (scene 4 hosts both the
// title and normal play). docs/direct-boot.md.
#include "smm2/frame.h"
#include "smm2/log.h"
#include "hk/ro/RoUtil.h"
#include "nn/fs.h"
#include <cstdint>
#include <cstdlib>
#include <cstring>

namespace smm2 { namespace directboot {

namespace {

constexpr uintptr_t OFF_PREPARE   = 0x1792070;
constexpr uintptr_t OFF_MODE      = 0x1790480;
constexpr uintptr_t OFF_SOURCE    = 0x1792890;
constexpr uintptr_t OFF_GO        = 0x1791020;
constexpr uintptr_t OFF_GPM       = 0x2C57D58;   // GamePhaseManager*; [[gpm]+0x30]+0x14 = scene mode (6 = title)
constexpr uint32_t TITLE_SETTLE   = 150;         // frames of title before the first request
constexpr uint32_t ROBO_SETTLE    = 300;         // frames in the Coursebot scene: its list load opens every used slot
constexpr uint32_t RETRY_EVERY    = 90;
constexpr int MAX_TRIES           = 8;

log::Logger s_log;
int s_course = -1;
int s_kind = 4;                 // cMyCourseToNormalPlay
uint32_t s_title_since = 0;
uint32_t s_last_try = 0;
int s_tries = 0;
int s_phase = 0;                // 0 title -> Coursebot (kind 1), 1 Coursebot -> play (kind s_kind)
uint32_t s_left_title = 0;
bool s_done = false;

uint32_t scene_mode(uintptr_t base) {
    uintptr_t gpm = *reinterpret_cast<uintptr_t*>(base + OFF_GPM);
    if (gpm < 0x1000000ull || gpm >= 0x3000000000ull) return 0;
    uintptr_t inner = *reinterpret_cast<uintptr_t*>(gpm + 0x30);
    if (inner < 0x1000000ull || inner >= 0x3000000000ull) return 0;
    return *reinterpret_cast<uint32_t*>(inner + 0x14);
}

void load_config() {
    nn::fs::FileHandle f;
    if (nn::fs::OpenFile(&f, "sd:/smm2-hooks/boot.txt", nn::fs::MODE_READ) != 0) return;
    static char buf[256];
    size_t n = 0;
    nn::fs::ReadFile(&n, f, 0, buf, sizeof(buf) - 1);
    nn::fs::CloseFile(f);
    buf[n] = '\0';
    char* p = buf;
    while (*p == ' ' || *p == '\t' || *p == '\r' || *p == '\n') p++;
    if (!std::strncmp(p, "coursebot", 9)) {
        char* end = nullptr;
        s_course = (int)std::strtol(p + 9, &end, 10);
        if (end && *end) { long k = std::strtol(end, nullptr, 10); if (k > 0) s_kind = (int)k; }
        s_log.writef("config coursebot %d kind %d\n", s_course, s_kind);
    } else if (*p && *p != '#') {
        s_log.writef("E,unknown line: %s\n", p);
    }
}

}  // namespace

void init() {
    s_log.init("directboot.log");
    load_config();
    s_log.flush();
}

static void request(uint32_t frame, uintptr_t base, int kind) {
    auto prepare = reinterpret_cast<void (*)(int, int64_t*)>(base + OFF_PREPARE);
    auto mode_fn = reinterpret_cast<void (*)(int)>(base + OFF_MODE);
    auto source  = reinterpret_cast<void (*)(int, int, int64_t*)>(base + OFF_SOURCE);
    auto go      = reinterpret_cast<uint64_t (*)(void*)>(base + OFF_GO);
    int64_t params[2] = {-1, -1};
    prepare(kind, params);
    mode_fn(kind);
    source(kind, s_course, params);
    uint64_t r = go(nullptr);
    s_tries++;
    s_last_try = frame;
    s_log.writef("%u,phase %d requested coursebot %d kind %d (try %d, go -> %llx)\n", frame, s_phase, s_course, kind, s_tries, (unsigned long long)r);
    s_log.flush();
}

void per_frame(uint32_t frame) {
    if (s_course < 0 || s_done) return;
    uintptr_t base = hk::ro::getMainModule()->range().start();
    uint32_t mode = scene_mode(base);
    if (s_phase == 0) {
        // Phase 0: from the title (scene mode 6) into the Coursebot scene, kind 1
        // (cTitleToRobo). Its list load opens every used slot into the cache the
        // play transition points at.
        if (mode != 6) {
            if (s_tries && s_title_since) {
                s_log.writef("%u,phase 0 done after %d tries (scene mode %u)\n", frame, s_tries, mode);
                s_log.flush();
                s_phase = 1; s_tries = 0; s_left_title = frame;
            }
            s_title_since = 0;
            return;
        }
        if (!s_title_since) s_title_since = frame;
        if (frame - s_title_since < TITLE_SETTLE) return;
        if (s_tries && frame - s_last_try < RETRY_EVERY) return;
        if (s_tries >= MAX_TRIES) { s_done = true; s_log.writef("%u,gave up in phase 0\n", frame); s_log.flush(); return; }
        request(frame, base, 1);
        return;
    }
    // Phase 1: give the Coursebot scene time to load its list, then play the entry.
    if (mode == 7) {
        s_log.writef("%u,in coursebot play\n", frame);
        s_log.flush();
        s_done = true;
        return;
    }
    if (frame - s_left_title < ROBO_SETTLE) return;
    if (s_tries && frame - s_last_try < RETRY_EVERY) return;
    if (s_tries >= MAX_TRIES) { s_done = true; s_log.writef("%u,gave up in phase 1 (scene mode %u)\n", frame, mode); s_log.flush(); return; }
    request(frame, base, s_kind);
}

}}  // namespace smm2::directboot
