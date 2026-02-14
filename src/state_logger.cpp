#include "smm2/log.h"
#include "smm2/player.h"
#include "smm2/frame.h"
#include "smm2/game_phase.h"
#include "smm2/status.h"
#include "hk/hook/Trampoline.h"
#include "hk/ro/RoUtil.h"

namespace smm2 {
namespace state_logger {

static log::Logger state_log;
static log::Logger field_log;
static uint32_t last_player_state = 0xFFFFFFFF;
static uintptr_t tracked_player = 0;

// Hook PlayerObject's changeState wrapper (sub_71015E3FB0)
// x0 = PlayerObject this, w1 = new state ID
static HkTrampoline<void, void*, uint32_t> playerChangeState_hook =
    hk::hook::trampoline([](void* player_obj, uint32_t new_state) -> void {
        auto player = reinterpret_cast<uintptr_t>(player_obj);

        // Read current state before change
        uint32_t old_state = player::read<uint32_t>(player, player::off::cur_state);

        // Call original
        playerChangeState_hook.orig(player_obj, new_state);

        // Log transition with physics snapshot
        float pos_x = player::read<float>(player, player::off::pos_x);
        float pos_y = player::read<float>(player, player::off::pos_y);
        float vel_x = player::read<float>(player, player::off::vel_x);
        float vel_y = player::read<float>(player, player::off::vel_y);

        state_log.writef("%u,%u,%u,%p,%.2f,%.2f,%.4f,%.4f\n",
            frame::current(), old_state, new_state,
            player_obj, pos_x, pos_y, vel_x, vel_y);

        // Always update tracked player (pointer can change between play sessions)
        tracked_player = player;
        status::set_player(player);

        // Mode detection: GamePhaseManager phase 3 covers both editor AND test-play
        // So we still need state transitions to distinguish them
        if (old_state == 16) {
            status::set_mode(1); // 16→any = entering play
        }
        if (new_state == 122) {
            status::set_mode(2); // goal
        }
        if (new_state == 9) {
            status::set_mode(3); // death
        }
        if ((old_state == 124 || old_state == 10) && new_state == 43) {
            status::set_mode(0); // back to editor after goal/death anim
        }
    });

// Also keep the generic StateMachine hook for all actors
static HkTrampoline<void, void*, uint32_t> changeState_hook =
    hk::hook::trampoline([](void* sm, uint32_t new_state) -> void {
        uint32_t old_state = *reinterpret_cast<uint32_t*>(
            reinterpret_cast<uintptr_t>(sm) + 0x08);
        changeState_hook.orig(sm, new_state);
    });

void init() {
    state_log.init("states.csv");
    state_log.write("frame,old_state,new_state,player_ptr,pos_x,pos_y,vel_x,vel_y\n", 62);
    playerChangeState_hook.installAtSym<"PlayerObject_changeState">();

    field_log.init("fields.csv");
    field_log.write("frame,state,state_frames,powerup_id,pos_x,pos_y,vel_x,vel_y,in_water\n", 69);
}

// Called every frame from main.cpp
void per_frame(uint32_t frame) {
    // Flush logs periodically
    if (frame % 300 == 0) {
        state_log.flush();
        field_log.flush();
    }

    // Dump player fields every 10 frames if we have a tracked player
    // Guard: skip if game phase is not playing (phase 3=editor/play, 4=coursebot play)
    // During scene transitions/rebuilds (theme change, etc), player pointer may be dangling
    int phase = smm2::game_phase::read_phase();
    if (tracked_player != 0 && frame % 10 == 0 && (phase == 3 || phase == 4)) {
        uint32_t state = player::read<uint32_t>(tracked_player, player::off::cur_state);
        uint32_t state_frames = player::read<uint32_t>(tracked_player, player::off::state_frames);
        uint32_t del_state = player::read<uint32_t>(tracked_player, player::off::powerup_id);
        float px = player::read<float>(tracked_player, player::off::pos_x);
        float py = player::read<float>(tracked_player, player::off::pos_y);
        float vx = player::read<float>(tracked_player, player::off::vel_x);
        float vy = player::read<float>(tracked_player, player::off::vel_y);
        uint8_t water = player::read<uint8_t>(tracked_player, player::off::in_water);

        field_log.writef("%u,%u,%u,%u,%.2f,%.2f,%.4f,%.4f,%u\n",
            frame, state, state_frames, del_state, px, py, vx, vy, water);
    }
}

void flush() {
    state_log.flush();
    field_log.flush();
}

} // namespace state_logger
} // namespace smm2
