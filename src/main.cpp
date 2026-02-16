#include "smm2/frame.h"
#include "nn/fs.h"

// Forward declarations for plugins
namespace smm2 { namespace state_logger {
    void init();
    void per_frame(uint32_t frame);
    void flush();
}}

namespace smm2 { namespace func_trace {
    void init();
    void flush();
}}

namespace smm2 { namespace reimpl {
    void init();
}}

namespace smm2 { namespace tas {
    void init();
}}

namespace smm2 { namespace status {
    void init();
    void update(uint32_t frame);
}}

namespace smm2 { namespace game_phase {
    void init();
    void per_frame(uint32_t frame);
}}

namespace smm2 { namespace course_data {
    void init();
}}

namespace smm2 { namespace actor_profile {
    void init();
}}

static void on_frame(uint32_t frame) {
    // smm2::state_logger::per_frame(frame);  // DISABLED — crashes during scene transitions
    smm2::game_phase::per_frame(frame);
    smm2::status::update(frame);

    // Flush logs periodically
    if (frame % 300 == 0) {
        smm2::func_trace::flush();
    }
}

extern "C" void hkMain() {
    nn::fs::MountSdCardForDebug("sd");
    // CreateDirectoryRecursively may not be available on all Ryujinx versions
    // The directory should already exist from prior runs, or be created manually
    nn::fs::CreateDirectory("sd:/smm2-hooks");

    // Init framework
    smm2::frame::init(on_frame);

    // Init plugins
    // Minimal config — bisecting crash
    // smm2::state_logger::init();  // DISABLED — changeState hook crashes during scene transitions
    // smm2::func_trace::init();    // 49 delegate hooks — known crash
    // smm2::reimpl::init();
    smm2::tas::init();              // hooks GetNpadStates (input injection)
    smm2::status::init();           // writes status.bin from procFrame_
    smm2::game_phase::init();      // reads GamePhaseManager — needed for scene detection
    smm2::course_data::init();     // hooks WriteFile to intercept BCD saves
    smm2::actor_profile::init();   // logs actor profile registrations + state names
}
