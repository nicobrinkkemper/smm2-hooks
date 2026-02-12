#include "smm2/status.h"
#include "smm2/player.h"
#include "nn/fs.h"
#include <cstring>

namespace smm2 {
namespace status {

static const char* STATUS_PATH = "sd:/smm2-hooks/status.bin";
static uintptr_t s_player = 0;

// GamePhaseManager singleton pointer
// At runtime: base + 0xB15BD58 contains a pointer to the manager
// Manager+0x?? contains the current phase enum
// Phase 4 = playing mode
// TODO: verify the exact read path via GDB

void set_player(uintptr_t player) {
    s_player = player;
}

void init() {
    nn::fs::DeleteFile(STATUS_PATH);
    nn::fs::CreateFile(STATUS_PATH, sizeof(StatusBlock));
}

void update(uint32_t frame) {
    StatusBlock blk;
    std::memset(&blk, 0, sizeof(blk));
    blk.frame = frame;
    blk.game_phase = 0; // TODO: read from GamePhaseManager once we verify the pointer chain

    if (s_player != 0) {
        blk.player_state = player::read<uint32_t>(s_player, player::off::cur_state);
        blk.powerup_id   = player::read<uint32_t>(s_player, player::off::powerup_id);
        blk.pos_x        = player::read<float>(s_player, player::off::pos_x);
        blk.pos_y        = player::read<float>(s_player, player::off::pos_y);
        blk.vel_x        = player::read<float>(s_player, player::off::vel_x);
        blk.vel_y        = player::read<float>(s_player, player::off::vel_y);
    }

    // Write directly (overwrite same position each frame)
    nn::fs::FileHandle f;
    if (nn::fs::OpenFile(&f, STATUS_PATH, nn::fs::MODE_WRITE) == 0) {
        nn::fs::WriteOption opt = {.flags = nn::fs::WRITE_OPTION_FLUSH};
        nn::fs::WriteFile(f, 0, &blk, sizeof(blk), opt);
        nn::fs::CloseFile(f);
    }
}

} // namespace status
} // namespace smm2
