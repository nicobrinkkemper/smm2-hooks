#include "smm2/course_data.h"
#include "smm2/log.h"
#include "nn/fs.h"
#include "hk/hook/Trampoline.h"
#include <cstring>

namespace smm2 {
namespace course_data {

// BCD format offsets (from toost level.ksy):
//   0x04: timer (s2)
//   0xF1: gamestyle (s2) — 0x314d=SMB1, 0x334d=SMB3, 0x574d=SMW, 0x5557=NSMBU, 0x5733=3DW
//   0xF3: name (UTF-16LE, 0x42 bytes)
//   0x200: overworld map — theme(u8), autoscroll_type(u8), boundary_type(u8), orientation(u8)
// Total encrypted BCD: 0x5BFD0 bytes (header 0x10 + data 0x5BFC0 + crypto 0x30)

static uint8_t  s_theme = 0xFF;
static uint16_t s_gamestyle = 0;
static char     s_name[64] = {};
static log::Logger s_log;
static bool s_log_init = false;

uint8_t theme() { return s_theme; }
uint16_t gamestyle() { return s_gamestyle; }
const char* course_name() { return s_name; }

// Parse BCD header from raw (decrypted) data
static void parse_bcd(const uint8_t* data, size_t size) {
    if (size < 0x210) return;
    
    // Sanity check: start_y and goal_y should be reasonable (0-27 for standard levels)
    if (data[0] > 30 || data[1] > 30) return;
    
    // Gamestyle at offset 0xF1
    s_gamestyle = data[0xF1] | (data[0xF2] << 8);
    
    // Validate gamestyle is one of the known values
    if (s_gamestyle != 0x314d && s_gamestyle != 0x334d && 
        s_gamestyle != 0x574d && s_gamestyle != 0x5557 && s_gamestyle != 0x5733)
        return;
    
    // Course name at offset 0xF3 (UTF-16LE)
    const uint16_t* name16 = reinterpret_cast<const uint16_t*>(data + 0xF3);
    int j = 0;
    for (int i = 0; i < 32 && name16[i]; i++) {
        if (name16[i] < 128) s_name[j++] = (char)name16[i];
        else s_name[j++] = '?';
    }
    s_name[j] = 0;
    
    // Theme at offset 0x200
    uint8_t t = data[0x200];
    if (t > 9) return; // Invalid theme
    s_theme = t;
    
    // Log
    if (!s_log_init) {
        s_log.init("course_data.csv");
        s_log.write("event,theme,gamestyle,name\n", 26);
        s_log_init = true;
    }
    
    static const char* theme_names[] = {"Ground","Underground","Castle","Airship",
        "Underwater","GhostHouse","Snow","Desert","Sky","Forest"};
    s_log.writef("bcd_write,%s,0x%x,%s\n", theme_names[s_theme], s_gamestyle, s_name);
    s_log.flush();
}

// Hook nn::fs::WriteFile to intercept BCD course data saves
// Signature: u32 WriteFile(FileHandle, s64 offset, const void* data, size_t size, const WriteOption&)
static HkTrampoline<uint32_t, nn::fs::FileHandle, int64_t, const void*, size_t, const nn::fs::WriteOption&> write_hook =
    hk::hook::trampoline([](nn::fs::FileHandle fh, int64_t offset, const void* data, size_t size, const nn::fs::WriteOption& opt) -> uint32_t {
        // Log writes > 1KB to discover game saves (filter out our own small writes)
        if (size > 1024) {
            if (!s_log_init) {
                s_log.init("course_data.csv");
                s_log.write("event,offset,size,first4\n", 24);
                s_log_init = true;
            }
            const uint8_t* b = reinterpret_cast<const uint8_t*>(data);
            s_log.writef("write,%lld,%zu,%02x%02x%02x%02x\n", offset, size, b[0], b[1], b[2], b[3]);
            s_log.flush();
        }
        
        // Check for BCD-sized writes
        if (offset == 0 && size >= 0x5BF00 && size <= 0x5C000) {
            const uint8_t* buf = reinterpret_cast<const uint8_t*>(data);
            
            // Check if this looks like encrypted BCD (starts with version 0x00000001)
            // or decrypted BCD (start_y, goal_y as small bytes)
            if (buf[0] <= 30 && buf[1] <= 30) {
                // Likely decrypted BCD
                parse_bcd(buf, size);
            }
            // Encrypted BCD starts with [01 00 00 00] — we can't parse that without keys
        }
        
        // Also check for smaller writes that might be the decrypted area data
        // The overworld map starts at 0x200 and is 0x2DEE0 bytes
        // If the game writes just the map portion...
        if (size >= 0x2DE00 && size <= 0x2DF00 && offset == 0) {
            const uint8_t* buf = reinterpret_cast<const uint8_t*>(data);
            // Map starts with theme(u8) + autoscroll(u8) + boundary(u8) + orient(u8)
            if (buf[0] <= 9 && buf[1] <= 4 && buf[2] <= 1 && buf[3] <= 1) {
                s_theme = buf[0];
                if (!s_log_init) {
                    s_log.init("course_data.csv");
                    s_log.write("event,theme,gamestyle,name\n", 26);
                    s_log_init = true;
                }
                static const char* theme_names[] = {"Ground","Underground","Castle","Airship",
                    "Underwater","GhostHouse","Snow","Desert","Sky","Forest"};
                s_log.writef("map_write,%s,,\n", theme_names[s_theme]);
                s_log.flush();
            }
        }
        
        return write_hook.orig(fh, offset, data, size, opt);
    });

void init() {
    write_hook.installAtSym<"_ZN2nn2fs9WriteFileENS0_10FileHandleElPKvmRKNS0_11WriteOptionE">();
}

} // namespace course_data
} // namespace smm2
