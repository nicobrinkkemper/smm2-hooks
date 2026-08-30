#include "smm2/probe.h"
#include "smm2/frame.h"
#include "smm2/log.h"
#include "hk/hook/Trampoline.h"
#include "hk/ro/RoUtil.h"
#include "nn/fs.h"
#include <cstdint>
#include <cstdlib>
#include <cstring>

// A function probe stands in for the hardware breakpoint Eden does not have:
// the hooked function runs unchanged, then one row per call records the
// integer argument registers and the requested fields behind x0. The config
// is read once at boot; see docs/probe.md for the file format and the rules
// (first instruction must not be PC-relative, hooked function must not
// return a float, a wrong field path can crash the game).

namespace smm2 {
namespace probe {

constexpr int MAX_HOOKS = 8;
constexpr int MAX_FIELDS = 24;
constexpr int MAX_CALLERS = 8;
constexpr int MAX_DEPTH = 4;
constexpr uintptr_t MAIN_BASE = 0x7100000000ull;
static const char* CONFIG_PATH = "sd:/smm2-hooks/probe.txt";

enum Type : uint8_t { T_U8, T_U16, T_U32, T_U64, T_F32 };

struct Field {
    char name[24];
    Type type;
    uint8_t depth;              // number of path steps; all but the last dereference
    uint8_t fromModule;         // path starts at the main module (@0x71... in probe.txt) instead of x0
    uint32_t path[MAX_DEPTH];
};

struct Hook {
    char name[24];
    uintptr_t vaddr;            // 0x71... address from functions.csv
    uint32_t every;             // log one call in `every`
    uint8_t callers;            // return addresses to log after the fields (callers=N, max MAX_CALLERS)
    uint32_t calls;
    int nfields;
    Field fields[MAX_FIELDS];
};

static Hook s_hooks[MAX_HOOKS];
static int s_nhooks = 0;
static log::Logger s_log;

// ── reading fields ────────────────────────────────────────────────────────

static bool plausible(uintptr_t p, unsigned align) {
    return p >= 0x8000000ull && p < 0x8000000000ull && (p & (align - 1)) == 0;
}

static bool read_field(uintptr_t x0, const Field& f, uint64_t& out) {
    // a module path starts at the main module's base, so its first step is the global's offset
    uintptr_t p = f.fromModule ? hk::ro::getMainModule()->range().start() : x0;
    for (int i = 0; i + 1 < f.depth; i++) {
        p += f.path[i];
        if (!plausible(p, 8)) return false;
        p = *reinterpret_cast<uintptr_t*>(p);
    }
    p += f.path[f.depth - 1];
    switch (f.type) {
    case T_U8:  if (!plausible(p, 1)) return false; out = *reinterpret_cast<uint8_t*>(p); return true;
    case T_U16: if (!plausible(p, 2)) return false; out = *reinterpret_cast<uint16_t*>(p); return true;
    case T_U32:
    case T_F32: if (!plausible(p, 4)) return false; out = *reinterpret_cast<uint32_t*>(p); return true;
    case T_U64: if (!plausible(p, 8)) return false; out = *reinterpret_cast<uint64_t*>(p); return true;
    }
    return false;
}

// The hook is entered by a branch, so the caller's x30 and x29 are intact at
// entry: lr0 is the call site, and the frame records ([fp] = previous fp,
// [fp+8] = its lr) walk the game's stack from there.
static uintptr_t module_relative(uintptr_t a) {
    const hk::ro::RoModule* mod = hk::ro::getMainModule();
    uintptr_t base = mod->range().start();
    if (a < base || a >= base + 0x2000000ull) return 0;
    return a - base + MAIN_BASE;
}

static void on_call(int idx, uint64_t x0, uint64_t x1, uint64_t x2, uint64_t x3,
                    uint64_t x4, uint64_t x5, uint64_t x6, uint64_t x7,
                    uintptr_t lr0, uintptr_t fp) {
    Hook& h = s_hooks[idx];
    h.calls++;
    if (h.every > 1 && (h.calls % h.every) != 0) return;
    s_log.writef("R,%u,%d,%llx,%llx,%llx,%llx,%llx,%llx,%llx,%llx", frame::current(), idx,
                 (unsigned long long)x0, (unsigned long long)x1, (unsigned long long)x2, (unsigned long long)x3,
                 (unsigned long long)x4, (unsigned long long)x5, (unsigned long long)x6, (unsigned long long)x7);
    for (int i = 0; i < h.nfields; i++) {
        uint64_t v;
        if (read_field(x0, h.fields[i], v))
            s_log.writef(",%llx", (unsigned long long)v);
        else
            s_log.write(",-", 2);
    }
    uintptr_t lr = lr0;
    for (int i = 0; i < h.callers; i++) {
        uintptr_t rel = module_relative(lr);
        if (rel) s_log.writef(",%llx", (unsigned long long)rel); else s_log.write(",-", 2);
        // next frame: our own record sits at fp; each record links to the previous
        if (!plausible(fp, 8) || !plausible(fp + 8, 8)) { lr = 0; fp = 0; continue; }
        lr = *reinterpret_cast<uintptr_t*>(fp + 8);
        fp = *reinterpret_cast<uintptr_t*>(fp);
    }
    s_log.write("\n", 1);
}

// ── trampoline slots ──────────────────────────────────────────────────────
// One static trampoline per slot; the lambda cannot capture, so the slot
// index is a template parameter. Eight integer args cover x0..x7; the
// original's x0 result is passed back unchanged.

template <int I>
struct Slot {
    static HkTrampoline<uint64_t, uint64_t, uint64_t, uint64_t, uint64_t, uint64_t, uint64_t, uint64_t, uint64_t> hook;
};

template <int I>
HkTrampoline<uint64_t, uint64_t, uint64_t, uint64_t, uint64_t, uint64_t, uint64_t, uint64_t, uint64_t> Slot<I>::hook =
    hk::hook::trampoline([](uint64_t x0, uint64_t x1, uint64_t x2, uint64_t x3,
                            uint64_t x4, uint64_t x5, uint64_t x6, uint64_t x7) -> uint64_t {
        uintptr_t lr0 = reinterpret_cast<uintptr_t>(__builtin_return_address(0));
        uintptr_t fp = reinterpret_cast<uintptr_t>(__builtin_frame_address(0));
        uint64_t r = Slot<I>::hook.orig(x0, x1, x2, x3, x4, x5, x6, x7);
        on_call(I, x0, x1, x2, x3, x4, x5, x6, x7, lr0, fp);
        return r;
    });

static bool install_slot(int idx, uintptr_t vaddr) {
    const hk::ro::RoModule* mod = hk::ro::getMainModule();
    ptr off = vaddr - MAIN_BASE;
    hk::Result rc;
    switch (idx) {
    case 0: rc = Slot<0>::hook.installAtOffset(mod, off); break;
    case 1: rc = Slot<1>::hook.installAtOffset(mod, off); break;
    case 2: rc = Slot<2>::hook.installAtOffset(mod, off); break;
    case 3: rc = Slot<3>::hook.installAtOffset(mod, off); break;
    case 4: rc = Slot<4>::hook.installAtOffset(mod, off); break;
    case 5: rc = Slot<5>::hook.installAtOffset(mod, off); break;
    case 6: rc = Slot<6>::hook.installAtOffset(mod, off); break;
    case 7: rc = Slot<7>::hook.installAtOffset(mod, off); break;
    default: return false;
    }
    return rc.succeeded();
}

// ── config ────────────────────────────────────────────────────────────────

static char* next_token(char*& s) {
    while (*s == ' ' || *s == '\t') s++;
    if (!*s) return nullptr;
    char* start = s;
    while (*s && *s != ' ' && *s != '\t') s++;
    if (*s) *s++ = '\0';
    return start;
}

static bool parse_type(const char* t, Type& out) {
    if (!std::strcmp(t, "u8")) { out = T_U8; return true; }
    if (!std::strcmp(t, "u16")) { out = T_U16; return true; }
    if (!std::strcmp(t, "u32")) { out = T_U32; return true; }
    if (!std::strcmp(t, "u64")) { out = T_U64; return true; }
    if (!std::strcmp(t, "f32")) { out = T_F32; return true; }
    return false;
}

static const char* type_name(Type t) {
    switch (t) {
    case T_U8: return "u8";
    case T_U16: return "u16";
    case T_U32: return "u32";
    case T_U64: return "u64";
    case T_F32: return "f32";
    }
    return "?";
}

static Hook* find_hook(const char* name) {
    for (int i = 0; i < s_nhooks; i++)
        if (!std::strcmp(s_hooks[i].name, name)) return &s_hooks[i];
    return nullptr;
}

static void copy_name(char* dst, size_t n, const char* src) {
    std::strncpy(dst, src, n - 1);
    dst[n - 1] = '\0';
}

// hook <name> <0x71...> [every=N]
static void parse_hook(char* rest) {
    if (s_nhooks >= MAX_HOOKS) { s_log.writef("E,too many hooks (max %d)\n", MAX_HOOKS); return; }
    char* name = next_token(rest);
    char* addr = next_token(rest);
    if (!name || !addr) { s_log.write("E,hook needs <name> <addr>\n", 27); return; }
    Hook& h = s_hooks[s_nhooks];
    std::memset(&h, 0, sizeof h);
    copy_name(h.name, sizeof h.name, name);
    h.vaddr = std::strtoull(addr, nullptr, 16);
    h.every = 1;
    for (char* opt = next_token(rest); opt; opt = next_token(rest))
        if (!std::strncmp(opt, "every=", 6)) h.every = (uint32_t)std::strtoul(opt + 6, nullptr, 10);
        else if (!std::strncmp(opt, "callers=", 8)) {
            unsigned long n = std::strtoul(opt + 8, nullptr, 10);
            h.callers = (uint8_t)(n > MAX_CALLERS ? MAX_CALLERS : n);
        }
    if (h.vaddr < MAIN_BASE || h.vaddr >= MAIN_BASE + 0x2000000ull) {
        s_log.writef("E,%s: address %s outside main\n", h.name, addr);
        return;
    }
    s_nhooks++;
}

// field <hook> <label> <type> <path>   path = 0x530>0x28 (deref all but last)
static void parse_field(char* rest) {
    char* hname = next_token(rest);
    char* label = next_token(rest);
    char* type = next_token(rest);
    char* path = next_token(rest);
    if (!hname || !label || !type || !path) { s_log.write("E,field needs <hook> <label> <type> <path>\n", 43); return; }
    Hook* h = find_hook(hname);
    if (!h) { s_log.writef("E,field %s: unknown hook %s\n", label, hname); return; }
    if (h->nfields >= MAX_FIELDS) { s_log.writef("E,%s: too many fields (max %d)\n", hname, MAX_FIELDS); return; }
    Field& f = h->fields[h->nfields];
    std::memset(&f, 0, sizeof f);
    copy_name(f.name, sizeof f.name, label);
    if (!parse_type(type, f.type)) { s_log.writef("E,field %s: bad type %s\n", label, type); return; }
    char* p = path;
    if (*p == '@') {            // @0x71...: a main-module address (functions.csv space), then the usual chain
        f.fromModule = 1;
        p++;
        char* sep = std::strchr(p, '>');
        if (sep) *sep = '\0';
        unsigned long long va = std::strtoull(p, nullptr, 16);
        if (va < MAIN_BASE) { s_log.writef("E,field %s: @address below main\n", label); return; }
        f.path[f.depth++] = (uint32_t)(va - MAIN_BASE);
        p = sep ? sep + 1 : nullptr;
    }
    while (p && *p) {
        if (f.depth >= MAX_DEPTH) { s_log.writef("E,field %s: path deeper than %d\n", label, MAX_DEPTH); return; }
        char* sep = std::strchr(p, '>');
        if (sep) *sep = '\0';
        f.path[f.depth++] = (uint32_t)std::strtoul(p, nullptr, 16);
        p = sep ? sep + 1 : nullptr;
    }
    if (f.depth == 0) { s_log.writef("E,field %s: empty path\n", label); return; }
    h->nfields++;
}

static void load_config() {
    nn::fs::FileHandle f;
    if (nn::fs::OpenFile(&f, CONFIG_PATH, nn::fs::MODE_READ) != 0) return;
    static char buf[8192];
    size_t n = 0;
    nn::fs::ReadFile(&n, f, 0, buf, sizeof(buf) - 1);
    nn::fs::CloseFile(f);
    buf[n] = '\0';

    char* line = buf;
    while (line && *line) {
        char* nl = std::strchr(line, '\n');
        if (nl) *nl = '\0';
        char* cr = std::strchr(line, '\r');
        if (cr) *cr = '\0';
        char* s = line;
        char* kw = next_token(s);
        if (kw && *kw != '#') {
            if (!std::strcmp(kw, "hook")) parse_hook(s);
            else if (!std::strcmp(kw, "field")) parse_field(s);
            else s_log.writef("E,unknown keyword %s\n", kw);
        }
        line = nl ? nl + 1 : nullptr;
    }
}

void init() {
    s_log.init("probe.log");
    s_log.write("V,1\n", 4);
    load_config();
    for (int i = 0; i < s_nhooks; i++) {
        Hook& h = s_hooks[i];
        bool ok = install_slot(i, h.vaddr);
        s_log.writef("H,%d,%s,%llx,%s", i, h.name, (unsigned long long)h.vaddr, ok ? "ok" : "failed");
        for (int j = 0; j < h.nfields; j++)
            s_log.writef(",%s:%s", h.fields[j].name, type_name(h.fields[j].type));
        for (int j = 0; j < h.callers; j++)
            s_log.writef(",lr%d:u64", j);
        s_log.write("\n", 1);
    }
    s_log.flush();
}

void flush() {
    s_log.flush();
}

} // namespace probe
} // namespace smm2
