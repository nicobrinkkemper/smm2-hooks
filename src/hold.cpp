// Frame hold: step the game one frame at a time for a frame-exact capture.
//
// With sd:/smm2-hooks/hold.txt present at boot, every frame ends by writing
// its number to held.bin and waiting until ack.bin (a u32 the host writes)
// reaches it. The host lets the game run by writing a large ack and steps it
// by acking each held frame after grabbing the window. A hold.txt reading
// "player" runs free until this play's player is first seen, so a capture
// starts on the play's first frame however long the boot took.
// tools/frame_capture.py.
#include "smm2/status.h"
#include "hk/svc/api.h"
#include "nn/fs.h"
#include <cstdint>
#include <cstring>

namespace smm2 { namespace hold {

namespace {

constexpr const char* HELD_PATH = "sd:/smm2-hooks/held.bin";
constexpr const char* ACK_PATH  = "sd:/smm2-hooks/ack.bin";

bool s_enabled = false;
bool s_from_player = false;

uint32_t read_ack() {
    nn::fs::FileHandle f;
    if (nn::fs::OpenFile(&f, ACK_PATH, nn::fs::MODE_READ) != 0) return 0xFFFFFFFFu;   // no ack file: run free
    uint32_t v = 0xFFFFFFFFu;
    size_t n = 0;
    nn::fs::ReadFile(&n, f, 0, &v, sizeof(v));
    nn::fs::CloseFile(f);
    return n == sizeof(v) ? v : 0xFFFFFFFFu;
}

void write_held(uint32_t frame) {
    nn::fs::FileHandle f;
    if (nn::fs::OpenFile(&f, HELD_PATH, nn::fs::MODE_WRITE) != 0) {
        nn::fs::CreateFile(HELD_PATH, sizeof(frame));
        if (nn::fs::OpenFile(&f, HELD_PATH, nn::fs::MODE_WRITE) != 0) return;
    }
    nn::fs::WriteOption opt = { .flags = nn::fs::WRITE_OPTION_FLUSH };
    nn::fs::WriteFile(f, 0, &frame, sizeof(frame), opt);
    nn::fs::CloseFile(f);
}

}  // namespace

void init() {
    nn::fs::FileHandle f;
    if (nn::fs::OpenFile(&f, "sd:/smm2-hooks/hold.txt", nn::fs::MODE_READ) != 0) return;
    char buf[16] = {};
    size_t n = 0;
    nn::fs::ReadFile(&n, f, 0, buf, sizeof(buf) - 1);
    nn::fs::CloseFile(f);
    s_enabled = true;
    s_from_player = std::strncmp(buf, "player", 6) == 0;
}

void per_frame(uint32_t frame) {
    if (!s_enabled) return;
    if (s_from_player && status::player_since() == 0) return;
    if (read_ack() >= frame) return;
    write_held(frame);
    while (read_ack() < frame) hk::svc::SleepThread(1000000);
}

}}  // namespace smm2::hold
