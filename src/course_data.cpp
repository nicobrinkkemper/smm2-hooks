#include "smm2/course_data.h"
#include "smm2/log.h"
#include "nn/fs.h"
#include "hk/hook/Trampoline.h"

namespace smm2 {
namespace course_data {

static uint8_t  s_theme = 0xFF;
static uint16_t s_gamestyle = 0;
static char     s_name[64] = {};

uint8_t theme() { return s_theme; }
uint16_t gamestyle() { return s_gamestyle; }
const char* course_name() { return s_name; }

static log::Logger s_log;
static bool s_inited = false;
static int s_count = 0;

// Hook OpenFile to trace what files get loaded (especially on title screen demo)
// Logs directly to file (initialized late by dump_open_log trigger)
static bool s_log_ready = false;

static HkTrampoline<uint32_t, nn::fs::FileHandle*, const char*, int> open_hook =
    hk::hook::trampoline([](nn::fs::FileHandle* handle, const char* path, int mode) -> uint32_t {
        // Only log after dump_open_log signals we're ready
        if (s_log_ready && path && s_count < 500) {
            // Skip our own files to avoid spam
            if (path[0] == 's' && path[1] == 'd' && path[2] == ':' && 
                path[3] == '/' && path[4] == 's' && path[5] == 'm') {
                // sd:/smm2-hooks/... skip
            } else {
                s_log.writef("open,%s,%d\n", path, mode);
                s_log.flush();
                s_count++;
            }
        }
        return open_hook.orig(handle, path, mode);
    });

// Call this after status system is running - enables OpenFile logging
void dump_open_log() {
    if (!s_inited) {
        s_log.init("course_data.csv");
        s_log.write("event,path,mode\n", 16);
        s_inited = true;
    }
    s_log_ready = true;
}

static HkTrampoline<uint32_t, nn::fs::FileHandle, int64_t, const void*, size_t, const nn::fs::WriteOption&> write_hook =
    hk::hook::trampoline([](nn::fs::FileHandle fh, int64_t offset, const void* data, size_t size, const nn::fs::WriteOption& opt) -> uint32_t {
        if (s_count < 50) {
            if (!s_inited) {
                s_log.init("course_data.csv");
                s_log.write("event,size,b0b1b2b3\n", 20);
                s_inited = true;
            }
            const uint8_t* b = (const uint8_t*)data;
            if (size >= 4) {
                s_log.writef("w,%d,%02x%02x%02x%02x\n", (int)size, b[0], b[1], b[2], b[3]);
            }
            s_count++;
            s_log.flush();
            
            // Check for BCD-sized writes
            if (size >= 0x5BF00 && size <= 0x5C000) {
                // Likely BCD data
                if (b[0] <= 30 && b[1] <= 30 && size >= 0x210) {
                    // Decrypted BCD
                    s_gamestyle = b[0xF1] | (b[0xF2] << 8);
                    s_theme = b[0x200];
                    s_log.writef("bcd,theme=%d,style=0x%x\n", s_theme, s_gamestyle);
                    s_log.flush();
                }
            }
        }
        
        return write_hook.orig(fh, offset, data, size, opt);
    });

void init() {
    open_hook.installAtSym<"_ZN2nn2fs8OpenFileEPNS0_10FileHandleEPKci">();
    write_hook.installAtSym<"_ZN2nn2fs9WriteFileENS0_10FileHandleElPKvmRKNS0_11WriteOptionE">();
}

} // namespace course_data
} // namespace smm2
