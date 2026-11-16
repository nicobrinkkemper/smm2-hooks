// Place: put the player at a point of the course being played.
//
//     place <x> <y> <n>
//
// holds the player at (x, y) for n frames and then lets go: he falls or
// stands from there as from any other spot. The line is read from
//     sd:/smm2-hooks/ctl.txt    while the game runs: polled every 4 frames and
//                               deleted once read, so write the file to send it;
//     sd:/smm2-hooks/boot.txt   at boot: it starts on the first frame of the
//                               first play's player.
// While held, the terrain collision (+0x49C bit 0) and the actor hits (+0x498
// bit 0x200) are off and the velocity is zero, so nothing between him and the
// point pushes back; both bits get their old value when the hold ends.
#include "smm2/place.h"
#include "smm2/status.h"
#include "nn/fs.h"
#include <cstdlib>
#include <cstring>

namespace smm2 { namespace place {

namespace {

constexpr const char* CTL_PATH = "sd:/smm2-hooks/ctl.txt";
constexpr uint32_t OFF_POS_X = 0x230, OFF_POS_Y = 0x234, OFF_VEL_X = 0x23C, OFF_VEL_Y = 0x240, OFF_SPEED = 0x274;
constexpr uint32_t OFF_HITS = 0x498, OFF_TERRAIN = 0x49C;
constexpr uint32_t HITS_OFF = 0x200, TERRAIN_OFF = 1;

float s_x = 0, s_y = 0;
uint32_t s_left = 0;            // frames still to hold
bool s_at_player = false;       // boot.txt's: waits for the play's player
uintptr_t s_held = 0;           // the player being held
uint32_t s_old_hits = 0, s_old_terrain = 0;

template <typename T> T& at(uintptr_t p, uint32_t off) { return *reinterpret_cast<T*>(p + off); }

void release() {
    if (s_held && status::player() == s_held) {
        at<uint32_t>(s_held, OFF_HITS) = (at<uint32_t>(s_held, OFF_HITS) & ~HITS_OFF) | (s_old_hits & HITS_OFF);
        at<uint32_t>(s_held, OFF_TERRAIN) = (at<uint32_t>(s_held, OFF_TERRAIN) & ~TERRAIN_OFF) | (s_old_terrain & TERRAIN_OFF);
    }
    s_held = 0;
}

void poll_ctl() {
    nn::fs::FileHandle f;
    if (nn::fs::OpenFile(&f, CTL_PATH, nn::fs::MODE_READ) != 0) return;
    char buf[128];
    size_t n = 0;
    nn::fs::ReadFile(&n, f, 0, buf, sizeof(buf) - 1);
    nn::fs::CloseFile(f);
    nn::fs::DeleteFile(CTL_PATH);
    buf[n] = '\0';
    for (char* line = std::strtok(buf, "\r\n"); line; line = std::strtok(nullptr, "\r\n")) {
        while (*line == ' ' || *line == '\t') line++;
        if (!std::strncmp(line, "place ", 6)) parse(line + 6, false);
    }
}

}  // namespace

bool parse(const char* args, bool at_player) {
    char* end = nullptr;
    float x = std::strtof(args, &end);
    if (end == args) return false;
    const char* p = end;
    float y = std::strtof(p, &end);
    if (end == p) return false;
    long n = std::strtol(end, nullptr, 10);
    if (n < 1) return false;
    release();
    s_x = x; s_y = y; s_left = (uint32_t)n; s_at_player = at_player;
    return true;
}

void init() {
    nn::fs::DeleteFile(CTL_PATH);   // a line left from an earlier run is not for this one
}

void per_frame(uint32_t frame) {
    if (frame % 4 == 0) poll_ctl();
    if (!s_left) return;
    uintptr_t player = status::player();
    if (!player) {
        if (!s_at_player) s_left = 0;   // nobody to place
        s_held = 0;
        return;
    }
    if (player != s_held) {
        s_held = player;
        s_old_hits = at<uint32_t>(player, OFF_HITS);
        s_old_terrain = at<uint32_t>(player, OFF_TERRAIN);
    }
    at<uint32_t>(player, OFF_HITS) |= HITS_OFF;
    at<uint32_t>(player, OFF_TERRAIN) |= TERRAIN_OFF;
    at<float>(player, OFF_POS_X) = s_x;
    at<float>(player, OFF_POS_Y) = s_y;
    at<float>(player, OFF_VEL_X) = 0;
    at<float>(player, OFF_VEL_Y) = 0;
    at<float>(player, OFF_SPEED) = 0;
    if (--s_left == 0) release();
}

}}  // namespace smm2::place
