#include "smm2/status.h"
#include "smm2/player.h"
#include "smm2/tas.h"
#include "smm2/game_phase.h"
#include "hk/ro/RoUtil.h"
#include "nn/fs.h"
#include <cstring>

namespace smm2 {
namespace status {

static const char* STATUS_PATH = "sd:/smm2-hooks/status.bin";
static uintptr_t s_player = 0;
static uint8_t s_mode = 0;  // 0=editor, 1=playing

void set_player(uintptr_t player) {
    s_player = player;
}

void set_mode(uint8_t mode) {
    s_mode = mode;
}

static bool is_death_state(uint32_t state) {
    // States 9, 10 = damage/death from state_logger observations
    // State 113 = death (from earlier captures)
    return state == 9 || state == 10 || state == 113;
}

static bool is_goal_state(uint32_t state) {
    // 122 = GoalPole grab, 124 = GoalBackJump/enter castle
    return state == 122 || state == 124;
}

void init() {
    nn::fs::DeleteFile(STATUS_PATH);
    nn::fs::CreateFile(STATUS_PATH, sizeof(StatusBlock));
}

void update(uint32_t frame) {
    StatusBlock blk;
    std::memset(&blk, 0, sizeof(blk));
    blk.frame = frame;
    blk.game_phase = s_mode; // 0=unknown, 1=playing, 2=goal, 3=dead
    blk.input_poll_count = tas::input_poll_count();
    blk.real_game_phase = game_phase::read_phase();

    // Guard: only read player fields when game phase is valid (3=editor/play, 4=coursebot)
    // During theme changes/scene transitions, player pointer may be dangling
    if (s_player != 0 && (blk.real_game_phase == 3 || blk.real_game_phase == 4)) {
        blk.player_state  = player::read<uint32_t>(s_player, player::off::cur_state);
        blk.powerup_id    = player::read<uint32_t>(s_player, player::off::powerup_id);
        blk.pos_x         = player::read<float>(s_player, player::off::pos_x);
        blk.pos_y         = player::read<float>(s_player, player::off::pos_y);
        blk.vel_x         = player::read<float>(s_player, player::off::vel_x);
        blk.vel_y         = player::read<float>(s_player, player::off::vel_y);
        blk.state_frames  = player::read<uint32_t>(s_player, player::off::state_frames);
        blk.in_water      = player::read<uint8_t>(s_player, player::off::in_water);
        blk.facing        = player::read<float>(s_player, 0x26C);
        blk.gravity       = player::read<float>(s_player, 0x27C);
        blk.buffered_action = player::read<uint32_t>(s_player, 0x4BC);
        blk.is_dead       = is_death_state(blk.player_state) ? 1 : 0;
        blk.is_goal       = is_goal_state(blk.player_state) ? 1 : 0;
        blk.has_player    = 1;
    }

    // Read course theme from sound manager global (elf+0x2c57090 -> ptr+0x58 = theme sound string)
    // Format: "V_<theme>" where theme = plain/underground/castle/airship/water/hauntedhouse/snow/desert/athletic/woods
    static uintptr_t s_base = 0;
    if (s_base == 0) s_base = hk::ro::getMainModule()->range().start();
    
    blk.course_theme = 0xFF; // unknown
    blk.game_style = 0;
    if (s_base != 0) {
        uintptr_t sound_mgr = *reinterpret_cast<uintptr_t*>(s_base + 0x2c57090);
        if (sound_mgr > 0x2000000000ULL && sound_mgr < 0x2200000000ULL) {
            const char* snd = reinterpret_cast<const char*>(sound_mgr + 0x58);
            // Skip "V_" prefix, match theme suffix
            if (snd[0] == 'V' && snd[1] == '_') {
                const char* n = snd + 2;
                     if (n[0]=='p' && n[1]=='l') blk.course_theme = 0;  // plain
                else if (n[0]=='u' && n[1]=='n') blk.course_theme = 1;  // underground
                else if (n[0]=='c' && n[1]=='a') blk.course_theme = 2;  // castle
                else if (n[0]=='a' && n[1]=='i') blk.course_theme = 3;  // airship
                else if (n[0]=='w' && n[1]=='a') blk.course_theme = 4;  // water
                else if (n[0]=='h' && n[1]=='a') blk.course_theme = 5;  // hauntedhouse
                else if (n[0]=='s' && n[1]=='n') blk.course_theme = 6;  // snow
                else if (n[0]=='d' && n[1]=='e') blk.course_theme = 7;  // desert
                else if (n[0]=='a' && n[1]=='t') blk.course_theme = 8;  // athletic (Sky)
                else if (n[0]=='w' && n[1]=='o') blk.course_theme = 9;  // woods (Forest)
            }
        }
    }

    nn::fs::FileHandle f;
    if (nn::fs::OpenFile(&f, STATUS_PATH, nn::fs::MODE_WRITE) == 0) {
        nn::fs::WriteOption opt = {.flags = nn::fs::WRITE_OPTION_FLUSH};
        nn::fs::WriteFile(f, 0, &blk, sizeof(blk), opt);
        nn::fs::CloseFile(f);
    }
}

} // namespace status
} // namespace smm2
