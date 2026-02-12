#include "smm2/game_phase.h"
#include "smm2/log.h"
#include "smm2/frame.h"
#include "smm2/status.h"
#include "hk/ro/RoUtil.h"

namespace smm2 {
namespace game_phase {

// GamePhaseManager* at virtual address 0x7102C57D58
// Runtime: base + 0x2C57D58
static uintptr_t s_gpm_addr = 0;
static log::Logger s_log;
static int s_last_phase = -1;

int read_phase() {
    if (s_gpm_addr == 0) return -1;
    
    // Read the global pointer: GamePhaseManager*
    uintptr_t gpm = *reinterpret_cast<uintptr_t*>(s_gpm_addr);
    if (gpm == 0) return -1;
    
    // Read inner pointer at +0x30
    uintptr_t inner = *reinterpret_cast<uintptr_t*>(gpm + 0x30);
    if (inner == 0) return -1;
    
    // Read phase at inner+0x1c
    int phase = *reinterpret_cast<int*>(inner + 0x1c);
    return phase;
}

void per_frame(uint32_t frame_num) {
    int phase = read_phase();
    
    // Log phase changes
    if (phase != s_last_phase) {
        s_log.writef("%u,%d,%d\n", frame_num, s_last_phase, phase);
        s_last_phase = phase;
        
        // Log phase for decomp research — don't override mode here
        // Course Maker test-play may stay in phase 3 (editor)
        // Mode detection still relies on state transitions in state_logger
    }
    
    if (frame_num % 300 == 0) {
        s_log.flush();
    }
}

void init() {
    // Resolve runtime address of gGamePhaseManager global
    uintptr_t base = hk::ro::getMainModule()->range().start();
    s_gpm_addr = base + 0x2C57D58;
    
    s_log.init("game_phase.csv");
    s_log.write("frame,old_phase,new_phase\n", 26);
}

} // namespace game_phase
} // namespace smm2
