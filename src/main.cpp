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

namespace smm2 { namespace xlink2_enum {
    void init();
    void flush();
}}

static void on_frame(uint32_t frame) {
    smm2::game_phase::per_frame(frame);
    smm2::status::update(frame);

    // Flush logs periodically
    if (frame % 300 == 0) {
        smm2::func_trace::flush();
        smm2::xlink2_enum::flush();
    }
}

extern "C" void hkMain() {
    nn::fs::MountSdCardForDebug("sd");
    nn::fs::CreateDirectory("sd:/smm2-hooks");

    // Init framework
    smm2::frame::init(on_frame);

    // Init plugins - ALL ENABLED
    smm2::tas::init();              // hooks GetNpadStates (input injection)
    smm2::status::init();           // writes status.bin, hooks PlayerObject_changeState
    smm2::game_phase::init();       // reads GamePhaseManager
    smm2::course_data::init();      // hooks WriteFile for BCD
    smm2::actor_profile::init();    // logs actor profiles + state names
    smm2::xlink2_enum::init();      // captures xlink2 enum definitions
}
