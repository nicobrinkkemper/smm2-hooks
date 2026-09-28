#include "smm2/ui_probe.h"
#include "smm2/log.h"
#include "hk/hook/Trampoline.h"
#include "hk/ro/RoUtil.h"
#include "nn/fs.h"
#include <cstdint>
#include <cstring>
#include <cstdio>

// Contract and original-binary tests: smm2-decomp plans/ui-text-probe.md.
// nn::ui2d::TextBox::DrawSelf, v3.0.3: 0x71004C38B0.
// This observes draw submissions, NOT final pixels, active screens or focus.
namespace smm2::ui_probe {
namespace {
constexpr unsigned MAX_ROWS = 128;
constexpr unsigned MAX_BYTES = 256;
constexpr unsigned MAX_DEPTH = 8;     // ancestors recorded above the TextBox
constexpr unsigned GEOM_BYTES = 0x60; // pane+0x30..0x90: local SRT, size, flags, global matrix
struct Row {
    uintptr_t pane;
    uint16_t length, capacity, bytes;
    uint8_t encoding, flags, alpha, depth;
    uint32_t tick;                    // poll tick of the latest draw
    uint32_t order;                   // TextBox draws before it in that tick: back to front
    uintptr_t root;                   // topmost ancestor: one per layout instance
    char name[24];
    char path[MAX_DEPTH][24];         // parent (+0x18) names, nearest first
    uint8_t geom[GEOM_BYTES];
    uint8_t text[MAX_BYTES];
};
uint32_t tick = 0;
uint32_t drawn = 0;                   // TextBox draws in the current tick

bool plausible(uintptr_t p) { return p >= 0x8000000 && p < 0x8000000000 && !(p & 7); }
Row rows[MAX_ROWS];
unsigned count = 0, dropped = 0, sequence = 0;
unsigned char lock = 0;
bool enabled = false;
char printPane[24] = {}, expected[128] = {};
uintptr_t printed = 0;
log::Logger logger;
constexpr char16_t MARKER[] = u"UI PROBE OK";
constexpr unsigned MARKER_LENGTH = sizeof(MARKER) / sizeof(char16_t) - 1;

template<typename T> T field(const void* pane, unsigned offset) {
    T value;
    std::memcpy(&value, static_cast<const char*>(pane) + offset, sizeof(value));
    return value;
}

void observe(void* pane) {
    // Never wait on the render thread, and never write SD files here.
    if (__atomic_test_and_set(&lock, __ATOMIC_ACQUIRE)) {
        __atomic_fetch_add(&dropped, 1u, __ATOMIC_RELAXED);
        return;
    }
    // DrawSelf itself requires length, font and material before drawing.
    const auto length = field<uint16_t>(pane, 0x112);
    const auto capacity = field<uint16_t>(pane, 0x110);
    const auto text = field<const uint8_t*>(pane, 0xD8);
    const auto encoding = field<uint8_t>(pane, 0x117);
    if (!length || !text || !field<uintptr_t>(pane, 0xF0) || !field<uintptr_t>(pane, 0x140)
        || !capacity || length >= capacity || encoding > 1) {
        __atomic_clear(&lock, __ATOMIC_RELEASE);
        return;
    }
    unsigned slot = 0;
    const auto address = reinterpret_cast<uintptr_t>(pane);
    while (slot < count && rows[slot].pane != address) ++slot;
    if (slot == MAX_ROWS) {
        __atomic_fetch_add(&dropped, 1u, __ATOMIC_RELAXED);
        __atomic_clear(&lock, __ATOMIC_RELEASE);
        return;
    }
    if (slot == count) ++count;
    Row& row = rows[slot];
    row.pane = address;
    row.length = length;
    row.capacity = capacity;
    row.encoding = encoding;
    row.flags = field<uint8_t>(pane, 0x58);
    row.alpha = field<uint8_t>(pane, 0x5A);
    std::memcpy(row.name, static_cast<const char*>(pane) + 0xB0, sizeof(row.name));
    row.tick = __atomic_load_n(&tick, __ATOMIC_RELAXED);
    row.order = drawn++;
    row.root = address;
    std::memcpy(row.geom, static_cast<const char*>(pane) + 0x30, GEOM_BYTES);
    // Pane::AppendChild (0x71004B24D0) stores the parent at +0x18.
    row.depth = 0;
    for (auto up = field<uintptr_t>(pane, 0x18); row.depth < MAX_DEPTH && plausible(up);
         up = field<uintptr_t>(reinterpret_cast<void*>(up), 0x18)) {
        std::memcpy(row.path[row.depth++], reinterpret_cast<const char*>(up) + 0xB0, 24);
        row.root = up;
    }
    const unsigned bytes = length * (encoding ? 1u : 2u);
    row.bytes = bytes < MAX_BYTES ? bytes : MAX_BYTES;
    std::memcpy(row.text, text, row.bytes);
    // An explicit pane name AND original ASCII string select one print test.
    // No save/file resource is changed. A normal boot restores the label.
    bool match = printPane[0] && !printed && encoding == 0
        && capacity > MARKER_LENGTH && std::strncmp(row.name, printPane, sizeof(row.name)) == 0
        && std::strlen(expected) == length;
    for (unsigned i = 0; match && i < length; ++i)
        match = text[2*i] == static_cast<uint8_t>(expected[i]) && text[2*i+1] == 0;
    if (match) printed = address;
    __atomic_clear(&lock, __ATOMIC_RELEASE);
    if (match) {
        using SetString = uint32_t (*)(void*, const char16_t*, uint16_t);
        const auto base = hk::ro::getMainModule()->range().start();
        // Original UTF-16 setter; the final argument is insertion offset, not length.
        reinterpret_cast<SetString>(base + 0x4C3BB0)(pane, MARKER, 0);
    }
}

// Coursebot list: sub_7101897360(screen, tile, slot) binds course `slot` to
// tile `tile` of the table at 0x7102CC0E78, whose entry 4R+C (R < 5, C < 4)
// is "/L_CourseDataList_0R/L_CourseBtn_0C"; it stores the slot at tile+0x68C.
constexpr unsigned TILES = 20;
int32_t tileSlot[TILES];
bool tilesSeen = false;
// sub_7101897190(screen, tile) empties a tile (its slot becomes -1).
HkTrampoline<void, void*, int> resetTile = hk::hook::trampoline(
    [](void* screen, int tile) -> void {
        resetTile.orig(screen, tile);
        if (tile >= 0 && static_cast<unsigned>(tile) < TILES) tileSlot[tile] = -1;
    });
HkTrampoline<void, void*, int, int> bindTile = hk::hook::trampoline(
    [](void* screen, int tile, int slot) -> void {
        bindTile.orig(screen, tile, slot);
        if (tile >= 0 && static_cast<unsigned>(tile) < TILES) { tileSlot[tile] = slot; tilesSeen = true; }
    });

// Menu focus. The game's buttons change focus through two methods of one
// class: sub_7101B61810(button, 1, ...) on the button losing it and
// sub_7101B615E0(button, 0, ...) on the one gaining it (every cursor move in
// the main menu, Coursebot grid, course details, tabs and dialogs). The
// button's pane path, e.g. "/L_CourseDataList_01/L_CourseBtn_01", is an
// inline string at *(button+0x58)+0xA0.
constexpr unsigned FOCUS_BYTES = 64;
char focusPath[FOCUS_BYTES] = {};
uint32_t focusTick = 0;
HkTrampoline<void, void*, unsigned, unsigned, unsigned, unsigned, void*> focusOn = hk::hook::trampoline(
    [](void* button, unsigned action, unsigned state, unsigned a4, unsigned a5, void* a6) -> void {
        focusOn.orig(button, action, state, a4, a5, a6);
        const auto holder = field<uintptr_t>(button, 0x58);
        if (!plausible(holder)) return;
        const auto* path = reinterpret_cast<const char*>(holder + 0xA0);
        unsigned n = 0;
        while (n < FOCUS_BYTES - 1 && path[n] >= 0x20 && path[n] < 0x7F) ++n;
        std::memcpy(focusPath, path, n);
        focusPath[n] = 0;
        focusTick = __atomic_load_n(&tick, __ATOMIC_RELAXED);
    });

// Screen state. The menus run Lp::Utl::StateMachine, like the actors: the
// Coursebot screens register Init, Idle, Appear, Disp, Open*/Disp*/Close*
// (dialogs), To* and Disappear (sub_71018801C0). changeState (0x71008B9320)
// stores the new state at machine+0x08 and counts frames in it at +0x0C;
// the state names sit in an array at machine+0x40 (16 bytes each, char* at
// +8, count at +0x38). The probe keeps the machines that changed state most
// recently.
constexpr unsigned MACHINES = 32;
constexpr int32_t MAX_STATES = 96;
// Everything read from a machine is read inside the game's own calls on it
// (change, execute, finalize): a screen torn down between two samples would
// otherwise be read after it was freed, which crashed Ryujinx.
struct Machine {
    uintptr_t machine;
    uint32_t changed, executed;   // ticks
    uint32_t caller;              // module offset of the changeState call
    int32_t state, frames;
    const char* name;             // static string in the game binary
    int32_t count;
    const char* names[MAX_STATES];
    bool described;
};
Machine machines[MACHINES];
unsigned char machinesLock = 0;

bool inModule(uintptr_t p) {
    const auto range = hk::ro::getMainModule()->range();
    return p >= range.start() && p < range.start() + range.size();
}
const char* stateName(uintptr_t m, int32_t state) {
    const auto count = field<int32_t>(reinterpret_cast<void*>(m), 0x38);
    const auto names = field<uintptr_t>(reinterpret_cast<void*>(m), 0x40);
    if (state < 0 || state >= count || !plausible(names)) return nullptr;
    const auto name = field<uintptr_t>(reinterpret_cast<void*>(names + 16 * state), 8);
    return inModule(name) ? reinterpret_cast<const char*>(name) : nullptr;
}
// Menu screens and their loaders, not actors: a machine with an Appear,
// Disp or LoadEnd state (actor machines name theirs cState_*).
bool menuMachine(uintptr_t m) {
    const auto count = field<int32_t>(reinterpret_cast<void*>(m), 0x38);
    for (int32_t i = 0; i < count && i < MAX_STATES; ++i) {
        const char* name = stateName(m, i);
        if (name && (!std::strcmp(name, "cAppear") || !std::strcmp(name, "cDisp") || !std::strcmp(name, "cLoadEnd")))
            return true;
    }
    return false;
}
Machine* tracked(uintptr_t m) {
    for (auto& e : machines) if (e.machine == m) return &e;
    return nullptr;
}
HkTrampoline<void, void*, int> changeState = hk::hook::trampoline(
    [](void* machine, int state) -> void {
        changeState.orig(machine, state);
        const auto m = reinterpret_cast<uintptr_t>(machine);
        const auto now = __atomic_load_n(&tick, __ATOMIC_RELAXED);
        if (__atomic_test_and_set(&machinesLock, __ATOMIC_ACQUIRE)) return;
        Machine* e = tracked(m);
        if (!e && menuMachine(m)) {
            e = &machines[0];
            for (auto& c : machines) if (c.changed < e->changed) e = &c;
            e->machine = m;
            e->count = field<int32_t>(machine, 0x38);
            if (e->count > MAX_STATES) e->count = MAX_STATES;
            for (int32_t i = 0; i < e->count; ++i) e->names[i] = stateName(m, i);
            e->described = false;
        }
        if (e) {
            const auto lr = reinterpret_cast<uintptr_t>(__builtin_return_address(0));
            e->changed = e->executed = now;
            e->caller = static_cast<uint32_t>(lr - hk::ro::getMainModule()->range().start());
            e->state = field<int32_t>(machine, 0x08);
            e->frames = field<int32_t>(machine, 0x0C);
            e->name = stateName(m, e->state);
        }
        __atomic_clear(&machinesLock, __ATOMIC_RELEASE);
    });
// sub_71008B9490 runs the current state once a frame: frames in state.
HkTrampoline<void, void*> executeState = hk::hook::trampoline(
    [](void* machine) -> void {
        const auto m = reinterpret_cast<uintptr_t>(machine);
        if (!__atomic_test_and_set(&machinesLock, __ATOMIC_ACQUIRE)) {
            if (Machine* e = tracked(m)) {
                e->executed = __atomic_load_n(&tick, __ATOMIC_RELAXED);
                e->frames = field<int32_t>(machine, 0x0C);
            }
            __atomic_clear(&machinesLock, __ATOMIC_RELEASE);
        }
        executeState.orig(machine);
    });
// StateMachine::finalize (0x71008B8F40): the machine is going away.
HkTrampoline<void, void*> finalizeMachine = hk::hook::trampoline(
    [](void* machine) -> void {
        const auto m = reinterpret_cast<uintptr_t>(machine);
        while (__atomic_test_and_set(&machinesLock, __ATOMIC_ACQUIRE)) {}
        if (Machine* e = tracked(m)) e->machine = 0;
        __atomic_clear(&machinesLock, __ATOMIC_RELEASE);
        finalizeMachine.orig(machine);
    });

HkTrampoline<void, void*, void*, void*> draw = hk::hook::trampoline(
    [](void* pane, void* drawInfo, void* commandBuffer) -> void {
        draw.orig(pane, drawInfo, commandBuffer);
        observe(pane);
    });

void hex(const void* src, unsigned n) {
    constexpr char digits[] = "0123456789abcdef";
    char out[MAX_BYTES * 2];
    const auto* bytes = static_cast<const uint8_t*>(src);
    for (unsigned i = 0; i < n; ++i) { out[2*i] = digits[bytes[i] >> 4]; out[2*i+1] = digits[bytes[i] & 15]; }
    logger.write(out, n * 2);
}
}

void init() {
    // Missing config means zero hooks installed and no rendering changes.
    // The log is created once: a second delete+create of the same file right
    // after the first can fail on Eden's host-backed SD card, and then every
    // later write is lost (seen 2026-09-28).
    nn::fs::FileHandle file;
    const auto openResult = nn::fs::OpenFile(&file, "sd:/smm2-hooks/ui-probe.txt", nn::fs::MODE_READ);
    if (openResult != 0) return;
    char config[256] = {};
    size_t size = 0;
    const auto rc = nn::fs::ReadFile(&size, file, 0, config, sizeof(config)-1);
    nn::fs::CloseFile(file);
    logger.init("ui-probe.log");
    auto bad = [](const char* why) { logger.writef("CONFIG_ERROR,%s\n", why); logger.flush(); };
    if (rc != 0 || !size || size >= sizeof(config)-1) return bad("read");
    // Eden can fill the buffer past the bytes it reports read (a "capture\n"
    // config failed the comparison on some boots), so end the string there.
    config[size] = 0;
    while (size && (config[size-1] == '\n' || config[size-1] == '\r')) config[--size] = 0;
    if (std::strcmp(config, "capture") != 0) {
        char* line = std::strchr(config, '\n');
        if (!line || std::strncmp(config, "print=", 6) != 0) {
            logger.write("CONFIG_BYTES,", 13);
            hex(config, size < 16 ? size : 16);
            logger.write("\n", 1);
            return bad("mode");
        }
        *line++ = 0;
        if (std::strncmp(line, "expect=", 7) != 0) return bad("expect");
        char* end = std::strchr(line, '\n');
        if (end) *end = 0;
        if (!config[6] || std::strlen(config+6) >= sizeof(printPane)
            || !line[7] || std::strlen(line+7) >= sizeof(expected)) return bad("length");
        std::strcpy(printPane, config+6);
        std::strcpy(expected, line+7);
    }
    logger.writef("UI_PROBE,6,303,draw_submission,mode=%s\n", printPane[0] ? "print" : "capture");
    auto result = draw.installAtOffset(hk::ro::getMainModule(), 0x4C38B0);
    // Hakkun aborts on installation failure when requested; explicitly report it here.
    if (result.failed()) {
        logger.write("INSTALL_FAILED\n", 15);
        logger.flush();
        return;
    }
    if (focusOn.installAtOffset(hk::ro::getMainModule(), 0x1B615E0).failed())
        logger.write("FOCUS_INSTALL_FAILED\n", 21);
    if (changeState.installAtOffset(hk::ro::getMainModule(), 0x8B9320).failed()
        || executeState.installAtOffset(hk::ro::getMainModule(), 0x8B9490).failed()
        || finalizeMachine.installAtOffset(hk::ro::getMainModule(), 0x8B8F40).failed())
        logger.write("STATE_INSTALL_FAILED\n", 21);
    for (auto& t : tileSlot) t = -1;
    if (resetTile.installAtOffset(hk::ro::getMainModule(), 0x1897190).failed())
        logger.write("TILE_RESET_INSTALL_FAILED\n", 26);
    if (bindTile.installAtOffset(hk::ro::getMainModule(), 0x1897360).failed())
        logger.write("TILE_INSTALL_FAILED\n", 20);
    enabled = true;
    logger.write("INSTALLED\n", 10);
    logger.flush();
}

void poll() {
    if (!enabled) return;
    static unsigned polls = 0;
    __atomic_add_fetch(&tick, 1u, __ATOMIC_RELAXED);
    __atomic_store_n(&drawn, 0u, __ATOMIC_RELAXED);
    if (__atomic_add_fetch(&polls, 1u, __ATOMIC_RELAXED) % 30 != 0) return;
    // poll may be reached via input and ordinary frame callbacks. Serialize
    // the consumer too; do not keep the row lock during filesystem calls.
    static unsigned char consumer = 0;
    if (__atomic_test_and_set(&consumer, __ATOMIC_ACQUIRE)) return;
    static Row batch[MAX_ROWS];
    if (__atomic_test_and_set(&lock, __ATOMIC_ACQUIRE)) {
        __atomic_clear(&consumer, __ATOMIC_RELEASE);
        return;
    }
    const unsigned n = count;
    const unsigned lost = __atomic_exchange_n(&dropped, 0u, __ATOMIC_RELAXED);
    const auto markerPane = printed;
    std::memcpy(batch, rows, n * sizeof(Row));
    count = 0;
    __atomic_clear(&lock, __ATOMIC_RELEASE);
    ++sequence;
    logger.writef("BEGIN,%u,%u,%u,%llx,%u\n", sequence, n, lost, (unsigned long long)markerPane, tick);
    for (unsigned i = 0; i < n; ++i) {
        const Row& r = batch[i];
        logger.writef("TEXT,%llx,%u,%u,%u,%u,%u,", (unsigned long long)r.pane,
            r.encoding, r.length, r.capacity, r.flags, r.alpha);
        hex(r.name, sizeof(r.name));
        logger.write(",", 1);
        hex(r.text, r.bytes);
        logger.writef(",%u,%u,%llx,", r.tick, r.order, (unsigned long long)r.root);
        for (unsigned d = 0; d < r.depth; ++d) {
            if (d) logger.write("/", 1);
            hex(r.path[d], sizeof(r.path[d]));
        }
        logger.write(",", 1);
        hex(r.geom, GEOM_BYTES);
        logger.write("\n", 1);
    }
    if (focusPath[0]) logger.writef("FOCUS,%u,%s\n", focusTick, focusPath);
    // A copy under the lock: the render and game threads write the table.
    static Machine copy[MACHINES];
    while (__atomic_test_and_set(&machinesLock, __ATOMIC_ACQUIRE)) {}
    std::memcpy(copy, machines, sizeof(copy));
    // Names again every 16 samples: the reader only scans the log's tail.
    const bool again = sequence % 16 == 0;
    for (auto& m : copy) if (again) m.described = false;
    for (auto& m : machines) if (m.machine) m.described = true;
    __atomic_clear(&machinesLock, __ATOMIC_RELEASE);
    for (const auto& m : copy) {
        if (!m.machine) continue;
        if (!m.described) {
            // Once per machine: every state name, which says what screen it is.
            logger.writef("MACHINE,%llx,%d,", (unsigned long long)m.machine, m.count);
            for (int32_t i = 0; i < m.count; ++i) {
                if (i) logger.write("|", 1);
                if (m.names[i]) logger.write(m.names[i], strnlen(m.names[i], 48));
            }
            logger.write("\n", 1);
        }
        logger.writef("STATE,%llx,%u,%x,%d,%d,%.40s,%u\n", (unsigned long long)m.machine, m.changed,
            m.caller, m.state, m.frames, m.name ? m.name : "", m.executed);
    }
    if (tilesSeen) {
        logger.write("SLOTS", 5);
        for (unsigned i = 0; i < TILES; ++i) logger.writef(",%d", tileSlot[i]);
        logger.write("\n", 1);
    }
    logger.writef("END,%u\n", sequence);
    logger.flush();
    __atomic_clear(&consumer, __ATOMIC_RELEASE);
}
}
