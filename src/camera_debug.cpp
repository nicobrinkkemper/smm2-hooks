#include "smm2/log.h"
#include "hk/ro/RoUtil.h"

namespace smm2 { namespace camera_debug {

static uintptr_t s_cam_global_addr = 0;
static uintptr_t s_last_cam = 0;
static log::Logger s_log;

uintptr_t get_camera() {
    if (s_cam_global_addr == 0) return 0;
    return *reinterpret_cast<uintptr_t*>(s_cam_global_addr);
}

void per_frame(uint32_t frame) {
    uintptr_t cam = get_camera();
    if (cam == 0) return;
    
    if (cam != s_last_cam) {
        s_log.writef("%u,camera_ptr,0x%lx\n", frame, cam);
        s_log.flush();
        s_last_cam = cam;
    }
    
    // Clamp activation bounds on all 5 view sub-objects
    // These are what sub_7100D96AB0 actually reads for actor spawning
    uintptr_t* view_ptrs = reinterpret_cast<uintptr_t*>(cam + 0x88);
    
    for (int slot = 0; slot < 5; slot++) {
        uintptr_t view = view_ptrs[slot];
        if (view == 0) continue;
        
        float* f = reinterpret_cast<float*>(view);
        
        // +0x14, +0x18: viewport dimensions (keep at original)
        f[0x14/4] = 384.0f;
        f[0x18/4] = 216.0f;
        f[0x1C/4] = 192.0f;  // half-width
        f[0x20/4] = 108.0f;  // half-height
        
        // +0x54..+0x60: activation BoundBox (original 1.5x)
        f[0x54/4] = -96.0f;
        f[0x58/4] = -54.0f;
        f[0x5C/4] = 480.0f;
        f[0x60/4] = 270.0f;
        
        // +0x6C, +0x70: viewport copy
        f[0x6C/4] = 384.0f;
        f[0x70/4] = 216.0f;
        
        // +0x74..+0x7C: screen margin BoundBox
        f[0x74/4] = -40.0f;
        f[0x78/4] = -16.0f;
        f[0x7C/4] = 424.0f;
    }
}

void init() {
    uintptr_t base = hk::ro::getMainModule()->range().start();
    s_cam_global_addr = base + 0x2C55080;
    s_log.init("camera_debug.csv");
    s_log.write("frame,field,value\n", 18);
}

}} // namespace smm2::camera_debug
