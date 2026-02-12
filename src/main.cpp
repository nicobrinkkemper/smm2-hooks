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

static void on_frame(uint32_t frame) {
    smm2::state_logger::per_frame(frame);

    // Flush logs periodically
    if (frame % 300 == 0) {
        smm2::func_trace::flush();
    }
}

extern "C" void hkMain() {
    nn::fs::MountSdCardForDebug("sd");
    nn::fs::CreateDirectoryRecursively("sd:/smm2-hooks");

    // Init framework
    smm2::frame::init(on_frame);

    // Init plugins
    smm2::state_logger::init();
    smm2::func_trace::init();
    smm2::reimpl::init();
    smm2::tas::init();  // loads tas.csv if present, otherwise no-op
}
