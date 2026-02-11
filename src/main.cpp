#include "smm2/frame.h"
#include "nn/fs.h"

// Forward declarations for plugins
namespace smm2 { namespace state_logger {
    void init();
    void per_frame(uint32_t frame);
    void flush();
}}

static void on_frame(uint32_t frame) {
    smm2::state_logger::per_frame(frame);
}

extern "C" void hkMain() {
    nn::fs::MountSdCardForDebug("sd");

    // Init framework
    smm2::frame::init(on_frame);

    // Init plugins
    smm2::state_logger::init();
}
