#include "smm2/course_data.h"
#include "smm2/log.h"
#include "nn/fs.h"
#include "hk/hook/Trampoline.h"
#include "hk/ro/RoUtil.h"
#include "smm2/frame.h"
#include <cstring>

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

// Reads of a whole course file (376768 bytes) with the caller chain: which
// game function loads a course, and when (Coursebot selection vs play).
static uintptr_t module_rel(uintptr_t a) {
    uintptr_t base = hk::ro::getMainModule()->range().start();
    return (a >= base && a < base + 0x2000000ull) ? a - base + 0x7100000000ull : 0;
}
static HkTrampoline<uint32_t, size_t*, nn::fs::FileHandle, int64_t, void*, size_t> read_hook =
    hk::hook::trampoline([](size_t* out, nn::fs::FileHandle fh, int64_t offset, void* data, size_t size) -> uint32_t {
        uintptr_t lr = reinterpret_cast<uintptr_t>(__builtin_return_address(0));
        uintptr_t fp = reinterpret_cast<uintptr_t>(__builtin_frame_address(0));
        uint32_t r = read_hook.orig(out, fh, offset, data, size);
        if (size >= 0x40000) {
            if (!s_inited) { s_log.init("course_data.csv"); s_inited = true; }
            s_log.writef("%u,read,%lld,%zu", frame::current(), (long long)offset, size);
            for (int i = 0; i < 8; i++) {
                uintptr_t rel = module_rel(lr);
                if (rel) s_log.writef(",%llx", (unsigned long long)rel); else s_log.write(",-", 2);
                if (fp < 0x1000000ull || fp >= 0x3000000000ull) break;
                lr = *reinterpret_cast<uintptr_t*>(fp + 8);
                fp = *reinterpret_cast<uintptr_t*>(fp);
            }
            s_log.write("\n", 1);
            s_log.flush();
        }
        return r;
    });

// The 4-arg ReadFile overload (no bytes-read out-pointer).
static HkTrampoline<uint32_t, nn::fs::FileHandle, int64_t, void*, size_t> read4_hook =
    hk::hook::trampoline([](nn::fs::FileHandle fh, int64_t offset, void* data, size_t size) -> uint32_t {
        uintptr_t lr = reinterpret_cast<uintptr_t>(__builtin_return_address(0));
        uintptr_t fp = reinterpret_cast<uintptr_t>(__builtin_frame_address(0));
        uint32_t r = read4_hook.orig(fh, offset, data, size);
        if (size >= 0x40000) {
            if (!s_inited) { s_log.init("course_data.csv"); s_inited = true; }
            s_log.writef("%u,read4,%lld,%zu", frame::current(), (long long)offset, size);
            for (int i = 0; i < 8; i++) {
                uintptr_t rel = module_rel(lr);
                if (rel) s_log.writef(",%llx", (unsigned long long)rel); else s_log.write(",-", 2);
                if (fp < 0x1000000ull || fp >= 0x3000000000ull) break;
                lr = *reinterpret_cast<uintptr_t*>(fp + 8);
                fp = *reinterpret_cast<uintptr_t*>(fp);
            }
            s_log.write("\n", 1);
            s_log.flush();
        }
        return r;
    });

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

// sd:/smm2-hooks/edit_records.req present: the records the editor holds now
// go to edit_records.bin and the request is removed (checked every 15
// frames). The editor's course areas sit at [qword_7102B2B718] + 0x28 +
// area * 0xC70; each starts with a sead OffsetList of record objects (count
// +0x10, node offset +0x14) that EditActor's constructor (sub_7100E8DAE0)
// fills through sub_7100FDD920. An object holds x, y (f32, the .bcd's
// tenths divided by 10) at +0x08, w, h (f32, tiles) at +0x14, then from
// +0x1c the .bcd record's own words: flags, child flags, extended flags,
// type, child type, link id, sub id (s16 each). Out: per area a u32 count,
// then count records of those 0x28 bytes from +0x08.
constexpr const char* RECORDS_REQ = "sd:/smm2-hooks/edit_records.req";
constexpr const char* RECORDS_OUT = "sd:/smm2-hooks/edit_records.bin";
constexpr uintptr_t OFF_EDIT_AREAS = 0x2B2B718;
constexpr int MAX_RECORDS = 2600;
constexpr size_t RECORD_BYTES = 0x28;

static bool heap_ptr(uintptr_t p) { return p >= 0x1000000ull && p < 0x3000000000ull; }

void poll_records(uint32_t frame) {
    if (frame % 15) return;
    nn::fs::FileHandle f;
    if (nn::fs::OpenFile(&f, RECORDS_REQ, nn::fs::MODE_READ) != 0) return;
    nn::fs::CloseFile(f);
    nn::fs::DeleteFile(RECORDS_REQ);
    uintptr_t areas = *reinterpret_cast<uintptr_t*>(hk::ro::getMainModule()->range().start() + OFF_EDIT_AREAS);
    if (!heap_ptr(areas)) return;
    static uint8_t out[2 * (4 + MAX_RECORDS * RECORD_BYTES)];
    size_t n = 0;
    for (int area = 0; area < 2; area++) {
        uintptr_t list = areas + 0x28 + area * 0xC70;
        int32_t count = *reinterpret_cast<int32_t*>(list + 0x10);
        int32_t offset = *reinterpret_cast<int32_t*>(list + 0x14);
        if (count < 0 || count > MAX_RECORDS) count = 0;
        size_t at = n;
        n += 4;
        uint32_t written = 0;
        uintptr_t node = *reinterpret_cast<uintptr_t*>(list + 8);
        while ((int32_t)written < count && heap_ptr(node) && node != list) {
            std::memcpy(out + n, reinterpret_cast<const void*>(node - offset + 8), RECORD_BYTES);
            n += RECORD_BYTES;
            written++;
            node = *reinterpret_cast<uintptr_t*>(node + 8);
        }
        std::memcpy(out + at, &written, 4);
    }
    nn::fs::DeleteFile(RECORDS_OUT);
    nn::fs::CreateFile(RECORDS_OUT, n);
    if (nn::fs::OpenFile(&f, RECORDS_OUT, nn::fs::MODE_WRITE) != 0) return;
    nn::fs::WriteOption opt = { .flags = nn::fs::WRITE_OPTION_FLUSH };
    nn::fs::WriteFile(f, 0, out, n, opt);
    nn::fs::CloseFile(f);
}

void init() {
    open_hook.installAtSym<"_ZN2nn2fs8OpenFileEPNS0_10FileHandleEPKci">();
    write_hook.installAtSym<"_ZN2nn2fs9WriteFileENS0_10FileHandleElPKvmRKNS0_11WriteOptionE">();
    // read_hook.installAtSym<"_ZN2nn2fs8ReadFileEPmNS0_10FileHandleElPvm">();   // suspect: hangs stub boots
    // read4_hook.installAtSym<"_ZN2nn2fs8ReadFileENS0_10FileHandleElPvm">();   // suspect: hangs stub boots
}

} // namespace course_data
} // namespace smm2
