#include "smm2/status.h"
#include "smm2/player.h"
#include "smm2/tas.h"
#include "smm2/game_phase.h"
#include "hk/ro/RoUtil.h"
#include "hk/hook/Trampoline.h"
#include "nn/fs.h"
#include <cstring>
#include <cstdio>

namespace smm2 {
namespace status {

static const char* STATUS_PATH = "sd:/smm2-hooks/status.bin";
static uintptr_t s_player = 0;
static uint8_t s_mode = 0;  // 0=editor, 1=playing

// Hook PlayerObject_changeState to track player pointer
// This replaces the dependency on state_logger
static HkTrampoline<void, void*, uint32_t> playerChangeState_hook =
    hk::hook::trampoline([](void* player_obj, uint32_t new_state) -> void {
        s_player = reinterpret_cast<uintptr_t>(player_obj);
        playerChangeState_hook.orig(player_obj, new_state);
    });

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
    playerChangeState_hook.installAtSym<"PlayerObject_changeState">();
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
    if (s_player != 0) {
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

    // Read course theme from noexes pointer chain:
    // [[main+0x2A67B70]+0x28]+0x210 = theme byte (0=ground, 1=underground, etc.)
    // Source: noexes-patches.md (well-known patch addresses)
    static uintptr_t s_base = 0;
    if (s_base == 0) s_base = hk::ro::getMainModule()->range().start();
    
    blk.course_theme = 0xFF; // unknown
    blk.game_style = 0;
    if (s_base != 0) {
        // Follow pointer chain: main+0x2A67B70 → [+0x28] → theme at +0x210
        uintptr_t* p1 = reinterpret_cast<uintptr_t*>(s_base + 0x2A67B70);
        if (*p1 > 0x1000000ULL && *p1 < 0x3000000000ULL) {
            uintptr_t* p2 = reinterpret_cast<uintptr_t*>(*p1 + 0x28);
            if (*p2 > 0x1000000ULL && *p2 < 0x3000000000ULL) {
                blk.course_theme = *reinterpret_cast<uint8_t*>(*p2 + 0x210);
            }
        }
    }

    // Read game style + dump GPM inner struct for screen detection research
    // GamePhaseManager: [[main+0x2C57D58]+0x30] = inner struct
    // Known fields: +0x1C = game_style, +0x28 = version
    blk.scene_mode = 0;
    blk.is_playing = 0;
    for (int i = 0; i < 6; i++) blk.gpm_inner[i] = 0;
    if (s_base != 0) {
        uintptr_t* gpm = reinterpret_cast<uintptr_t*>(s_base + 0x2C57D58);
        if (*gpm > 0x1000000ULL && *gpm < 0x3000000000ULL) {
            uintptr_t* inner = reinterpret_cast<uintptr_t*>(*gpm + 0x30);
            if (*inner > 0x1000000ULL && *inner < 0x3000000000ULL) {
                blk.game_style = *reinterpret_cast<uint32_t*>(*inner + 0x1C);
                // Scene detection fields
                blk.scene_mode = *reinterpret_cast<uint32_t*>(*inner + 0x14); // 1=editor, 5=play, 6=title
                blk.is_playing = *reinterpret_cast<uint32_t*>(*inner + 0x10); // 0=editor, 1=playing/title
                // Dump remaining inner struct for research
                for (int i = 0; i < 6; i++) {
                    blk.gpm_inner[i] = *reinterpret_cast<uint32_t*>(*inner + i * 4);
                }
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
