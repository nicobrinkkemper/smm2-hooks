#include "smm2/frame.h"
#include "nn/fs.h"

// Forward declarations for plugins
namespace smm2 { namespace state_logger {
    void init();
    void flush();
}}

static void on_frame(uint32_t frame) {
    // Flush logs every 300 frames (~5 seconds at 60fps)
    if (frame % 300 == 0) {
        smm2::state_logger::flush();
    }
}

extern "C" void hkMain() {
    nn::fs::MountSdCardForDebug("sd");

    // Init framework
    smm2::frame::init(on_frame);

    // Init plugins
    smm2::state_logger::init();
}
