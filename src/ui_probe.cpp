#include "smm2/ui_probe.h"
#include "smm2/tas.h"
#include "hk/hook/Trampoline.h"
#include "hk/ro/RoUtil.h"
#include "nn/fs.h"
#include <cstdarg>
#include <cstdint>
#include <cstdio>
#include <cstring>

// What the menus show, which control has the focus and which state each
// menu screen is in, rewritten to sd:/smm2-hooks/ui-screen.txt every
// SAMPLE_FRAMES frames. docs/ui-probe.md has the format and the evidence
// behind every address. v3.0.3 only.
namespace smm2::ui_probe {
namespace {
constexpr const char* CONFIG_PATH = "sd:/smm2-hooks/ui-probe.txt";
constexpr const char* SCREEN_PATH = "sd:/smm2-hooks/ui-screen.txt";
constexpr unsigned SAMPLE_FRAMES = 6;

uint32_t tick = 0;  // poll() calls, one per frame
bool enabled = false;

template<typename T> T field(const void* base, unsigned offset) {
    T value;
    std::memcpy(&value, static_cast<const char*>(base) + offset, sizeof(value));
    return value;
}
template<typename T> T field(uintptr_t base, unsigned offset) {
    return field<T>(reinterpret_cast<const void*>(base), offset);
}
bool plausible(uintptr_t p) { return p >= 0x8000000 && p < 0x8000000000 && !(p & 7); }
bool inModule(uintptr_t p) {
    const auto range = hk::ro::getMainModule()->range();
    return p >= range.start() && p < range.start() + range.size();
}
void lock(unsigned char& flag) { while (__atomic_test_and_set(&flag, __ATOMIC_ACQUIRE)) {} }
void unlock(unsigned char& flag) { __atomic_clear(&flag, __ATOMIC_RELEASE); }

// -- text: every nn::ui2d::TextBox drawn (TextBox::DrawSelf, 0x71004C38B0) --
constexpr unsigned MAX_ROWS = 128;
constexpr unsigned MAX_TEXT = 256;   // bytes
constexpr unsigned MAX_DEPTH = 8;    // ancestors
constexpr unsigned NAME = 24;        // Pane name, char[24] at +0xB0
struct Row {
    uintptr_t pane, root;            // root = topmost ancestor: one per layout instance
    uint32_t tick, order;            // order = TextBox draws before it in that tick
    float x, y, scale;               // global matrix at +0x70: tx +0x7C, ty +0x8C, sx +0x70
    uint16_t length, bytes;
    uint8_t encoding, depth;
    char name[NAME];
    char path[MAX_DEPTH][NAME];      // parent (+0x18) names, nearest first
    uint8_t text[MAX_TEXT];
};
Row rows[MAX_ROWS];
unsigned rowCount = 0, dropped = 0, drawnThisTick = 0;
unsigned char rowsLock = 0;

void observe(void* pane) {
    // The render thread never waits: a contended draw is counted and skipped.
    if (__atomic_test_and_set(&rowsLock, __ATOMIC_ACQUIRE)) {
        __atomic_fetch_add(&dropped, 1u, __ATOMIC_RELAXED);
        return;
    }
    // UTF-16 (or byte) text at +0xD8, capacity +0x110, length +0x112,
    // encoding +0x117; DrawSelf itself needs the font (+0xF0) and material (+0x140).
    const auto length = field<uint16_t>(pane, 0x112);
    const auto capacity = field<uint16_t>(pane, 0x110);
    const auto text = field<const uint8_t*>(pane, 0xD8);
    const auto encoding = field<uint8_t>(pane, 0x117);
    const auto address = reinterpret_cast<uintptr_t>(pane);
    unsigned slot = 0;
    while (slot < rowCount && rows[slot].pane != address) ++slot;
    if (!length || !text || !field<uintptr_t>(pane, 0xF0) || !field<uintptr_t>(pane, 0x140)
        || length >= capacity || encoding > 1 || slot == MAX_ROWS) {
        if (slot == MAX_ROWS) __atomic_fetch_add(&dropped, 1u, __ATOMIC_RELAXED);
        unlock(rowsLock);
        return;
    }
    if (slot == rowCount) ++rowCount;
    Row& row = rows[slot];
    row.pane = row.root = address;
    row.tick = tick;
    row.order = drawnThisTick++;
    row.x = field<float>(pane, 0x7C);
    row.y = field<float>(pane, 0x8C);
    row.scale = field<float>(pane, 0x70);
    row.length = length;
    row.encoding = encoding;
    std::memcpy(row.name, static_cast<const char*>(pane) + 0xB0, NAME);
    row.depth = 0;
    for (auto up = field<uintptr_t>(pane, 0x18); row.depth < MAX_DEPTH && plausible(up);
         up = field<uintptr_t>(up, 0x18)) {
        std::memcpy(row.path[row.depth++], reinterpret_cast<const char*>(up) + 0xB0, NAME);
        row.root = up;
    }
    const unsigned bytes = length * (encoding ? 1u : 2u);
    row.bytes = bytes < MAX_TEXT ? bytes : MAX_TEXT;
    std::memcpy(row.text, text, row.bytes);
    unlock(rowsLock);
}
HkTrampoline<void, void*, void*, void*> draw = hk::hook::trampoline(
    [](void* pane, void* drawInfo, void* commandBuffer) -> void {
        draw.orig(pane, drawInfo, commandBuffer);
        observe(pane);
    });

// Input per button. A screen switches its buttons' input on and off with
// sub_7100761190(button, player, on): the main menu's Disp state turns it on
// two frames in, so a screen can be in Disp and still ignore a press. This
// remembers the last switch for player 1 (index 0) of the buttons it saw.
constexpr unsigned BUTTONS = 128;
struct ButtonInput { uintptr_t button; bool on; };
ButtonInput buttonInput[BUTTONS];
unsigned buttonNext = 0;
uint32_t inputOnTick = 0, inputOffTick = 0;  // the last switch either way, any button
// The byte itself: player 1's handler in the list at button+0x228 (count
// +0x1FC) has it at +0x3A. Read only inside the game's calls on the button.
int readInput(uintptr_t b) {
    const auto list = field<uintptr_t>(b, 0x228);
    const auto count = field<int32_t>(b, 0x1FC);
    for (int32_t i = 0; plausible(list) && i < count && i < 64; ++i) {
        const auto handler = field<uintptr_t>(list + 8 * i, 0);
        if (plausible(handler) && field<uint32_t>(handler, 0x20) == 0) return field<uint8_t>(handler, 0x3A) & 1;
    }
    return -1;
}
void rememberInput(uintptr_t b, bool on) {
    for (auto& e : buttonInput)
        if (e.button == b) { e.on = on; return; }
    buttonInput[buttonNext++ % BUTTONS] = {b, on};
}
HkTrampoline<void, void*, unsigned, bool> setInput = hk::hook::trampoline(
    [](void* button, unsigned player, bool on) -> void {
        setInput.orig(button, player, on);
        if (player != 0) return;
        (on ? inputOnTick : inputOffTick) = tick;
        rememberInput(reinterpret_cast<uintptr_t>(button), on);
    });
// -- focus ----------------------------------------------------------------
// The game's buttons change focus through two methods of one class:
// sub_7101B61810(button, 1, ...) on the button losing it and
// sub_7101B615E0(button, 0, ...) on the one gaining it. The button's pane
// path, e.g. "/L_CourseDataList_01/L_CourseBtn_01", is an inline string at
// *(button+0x58)+0xA0.
constexpr unsigned FOCUS = 64;
char focusPath[FOCUS] = {};
uint32_t focusTick = 0;  // the frame of the last focus call
uintptr_t focusButton = 0;
HkTrampoline<void, void*, unsigned, unsigned, unsigned, unsigned, void*> focusOn = hk::hook::trampoline(
    [](void* button, unsigned action, unsigned state, unsigned a4, unsigned a5, void* a6) -> void {
        focusOn.orig(button, action, state, a4, a5, a6);
        const auto holder = field<uintptr_t>(button, 0x58);
        if (!plausible(holder)) return;
        const auto* path = reinterpret_cast<const char*>(holder + 0xA0);
        unsigned n = 0;
        while (n < FOCUS - 1 && path[n] > 0x20 && path[n] < 0x7F && path[n] != ',') ++n;
        std::memcpy(focusPath, path, n);
        focusPath[n] = 0;
        focusButton = reinterpret_cast<uintptr_t>(button);
        focusTick = tick;
        // A button at a freed one's address must not inherit its input state.
        const int on = readInput(focusButton);
        if (on >= 0) rememberInput(focusButton, on);
    });

// 1 on, 0 off, -1 never switched since boot.
int focusInput() {
    for (const auto& e : buttonInput)
        if (focusButton && e.button == focusButton) return e.on;
    return -1;
}

// -- Coursebot slots --------------------------------------------------------
// sub_7101897360(screen, tile, slot) binds course `slot` to entry `tile` of
// the Coursebot list's table at 0x7102CC0E78 (entry 4R+C is
// "/L_CourseDataList_0R/L_CourseBtn_0C"; the game keeps the slot at
// tile+0x68C), empty slots included; sub_7101897190(screen, tile) empties one.
constexpr unsigned TILES = 20;
int32_t tileSlot[TILES];
bool tilesSeen = false;
HkTrampoline<void, void*, int, int> bindTile = hk::hook::trampoline(
    [](void* screen, int tile, int slot) -> void {
        bindTile.orig(screen, tile, slot);
        if (tile >= 0 && static_cast<unsigned>(tile) < TILES) { tileSlot[tile] = slot; tilesSeen = true; }
    });
HkTrampoline<void, void*, int> resetTile = hk::hook::trampoline(
    [](void* screen, int tile) -> void {
        resetTile.orig(screen, tile);
        if (tile >= 0 && static_cast<unsigned>(tile) < TILES) tileSlot[tile] = -1;
    });

// -- screen state -----------------------------------------------------------
// The menus run Lp::Utl::StateMachine like the actors. A machine keeps its
// state at +0x08 and the frames spent in it at +0x0C; the state names (the
// part after "::", e.g. "cDisp") sit in an array at +0x40, 16 bytes each
// with the char* at +8, count at +0x38. Everything is read inside the
// game's own calls on the machine (change, execute, finalize): a screen
// torn down between samples must not be read after it is freed.
constexpr unsigned MACHINES = 32;
constexpr int32_t MAX_STATES = 96;
struct Machine {
    uintptr_t machine;
    uint32_t changed, executed;   // ticks
    uint32_t appeared;            // tick it last entered an Appear state: a new showing
    int32_t state, frames, count;
    const char* names[MAX_STATES];  // static strings in the game binary
};
Machine machines[MACHINES];
unsigned char machinesLock = 0;

const char* stateName(uintptr_t m, int32_t state) {
    const auto names = field<uintptr_t>(m, 0x40);
    if (state < 0 || state >= field<int32_t>(m, 0x38) || !plausible(names)) return nullptr;
    const auto name = field<uintptr_t>(names + 16 * state, 8);
    return inModule(name) ? reinterpret_cast<const char*>(name) : nullptr;
}
// Menu screens and their loaders, not actors: a machine with an Appear,
// Disp or LoadEnd state (actor machines name theirs cState_*).
bool menuMachine(uintptr_t m) {
    const auto count = field<int32_t>(m, 0x38);
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
// Lp::Utl::StateMachine::changeState (0x71008B9320)
HkTrampoline<void, void*, int> changeState = hk::hook::trampoline(
    [](void* machine, int state) -> void {
        changeState.orig(machine, state);
        const auto m = reinterpret_cast<uintptr_t>(machine);
        lock(machinesLock);
        Machine* e = tracked(m);
        if (!e && menuMachine(m)) {
            e = &machines[0];
            for (auto& c : machines) if (c.changed < e->changed) e = &c;
            e->machine = m;
            e->appeared = 0;
            e->count = field<int32_t>(m, 0x38) < MAX_STATES ? field<int32_t>(m, 0x38) : MAX_STATES;
            for (int32_t i = 0; i < e->count; ++i) e->names[i] = stateName(m, i);
        }
        if (e) {
            e->changed = e->executed = tick;
            const auto state = field<int32_t>(m, 0x08);
            const char* name = state >= 0 && state < e->count ? e->names[state] : nullptr;
            if (name && std::strstr(name, "Appear")) e->appeared = tick;
            e->state = state;
            e->frames = field<int32_t>(m, 0x0C);
        }
        unlock(machinesLock);
    });
// sub_71008B9490 runs the current state once a frame.
HkTrampoline<void, void*> executeState = hk::hook::trampoline(
    [](void* machine) -> void {
        const auto m = reinterpret_cast<uintptr_t>(machine);
        lock(machinesLock);
        if (Machine* e = tracked(m)) {
            e->executed = tick;
            e->frames = field<int32_t>(m, 0x0C);
        }
        unlock(machinesLock);
        executeState.orig(machine);
    });
// Lp::Utl::StateMachine::finalize (0x71008B8F40): the machine goes away.
HkTrampoline<void, void*> finalizeMachine = hk::hook::trampoline(
    [](void* machine) -> void {
        lock(machinesLock);
        if (Machine* e = tracked(reinterpret_cast<uintptr_t>(machine))) e->machine = 0;
        unlock(machinesLock);
        finalizeMachine.orig(machine);
    });

// -- the snapshot file --------------------------------------------------------
char out[128 * 1024];
unsigned outLength = 0;
void put(const char* fmt, ...) __attribute__((format(printf, 1, 2)));
void put(const char* fmt, ...) {
    if (outLength >= sizeof(out)) return;
    va_list args;
    va_start(args, fmt);
    const int n = std::vsnprintf(out + outLength, sizeof(out) - outLength, fmt, args);
    va_end(args);
    if (n > 0) outLength = outLength + n < sizeof(out) ? outLength + n : sizeof(out);
}
void putHex(const uint8_t* bytes, unsigned n) {
    constexpr char digits[] = "0123456789abcdef";
    for (unsigned i = 0; i < n && outLength + 2 < sizeof(out); ++i) {
        out[outLength++] = digits[bytes[i] >> 4];
        out[outLength++] = digits[bytes[i] & 15];
    }
}
// Pane names are identifiers; anything else becomes '?' so it cannot break a line.
void putName(const char* name) {
    for (unsigned i = 0; i < NAME && name[i] && outLength < sizeof(out); ++i) {
        const char c = name[i];
        const bool ok = (c >= '0' && c <= '9') || (c >= 'A' && c <= 'Z') || (c >= 'a' && c <= 'z') || c == '_';
        out[outLength++] = ok ? c : '?';
    }
}
// Rewritten in place, like status.bin; BEGIN and END carry the same sequence
// so a reader can tell a torn read.
void writeScreen() {
    nn::fs::FileHandle file;
    if (nn::fs::OpenFile(&file, SCREEN_PATH, nn::fs::MODE_WRITE) != 0) return;
    nn::fs::SetFileSize(file, outLength);
    nn::fs::WriteOption option = {.flags = nn::fs::WRITE_OPTION_FLUSH};
    nn::fs::WriteFile(file, 0, out, outLength, option);
    nn::fs::CloseFile(file);
}
void fail(const char* why) {
    outLength = 0;
    put("ERROR,%s\n", why);
    writeScreen();
}
}  // namespace

void init() {
    // No config file: nothing is hooked.
    nn::fs::FileHandle file;
    if (nn::fs::OpenFile(&file, CONFIG_PATH, nn::fs::MODE_READ) != 0) return;
    char config[64] = {};
    size_t size = 0;
    const auto rc = nn::fs::ReadFile(&size, file, 0, config, sizeof(config) - 1);
    nn::fs::CloseFile(file);
    nn::fs::DeleteFile(SCREEN_PATH);
    nn::fs::CreateFile(SCREEN_PATH, 0);
    // Eden can fill the buffer past the bytes it reports read, so the
    // string ends at `size`.
    if (rc != 0 || size >= sizeof(config)) return fail("config read");
    config[size] = 0;
    while (size && (config[size - 1] == '\n' || config[size - 1] == '\r')) config[--size] = 0;
    if (std::strcmp(config, "capture") != 0) return fail("config is not 'capture'");

    const auto* module = hk::ro::getMainModule();
    if (draw.installAtOffset(module, 0x4C38B0).failed()
        || focusOn.installAtOffset(module, 0x1B615E0).failed()
        || setInput.installAtOffset(module, 0x761190).failed()
        || bindTile.installAtOffset(module, 0x1897360).failed()
        || resetTile.installAtOffset(module, 0x1897190).failed()
        || changeState.installAtOffset(module, 0x8B9320).failed()
        || executeState.installAtOffset(module, 0x8B9490).failed()
        || finalizeMachine.installAtOffset(module, 0x8B8F40).failed())
        return fail("hook install");
    for (auto& slot : tileSlot) slot = -1;
    enabled = true;
}

void poll() {
    if (!enabled) return;
    // poll() is reached from both the frame and the input-poll callbacks.
    static unsigned char polling = 0;
    if (__atomic_test_and_set(&polling, __ATOMIC_ACQUIRE)) return;
    ++tick;
    // The last frame the game read a button held: a press's answer is timed from it.
    static uint32_t buttonsTick = 0;
    if (tas::seen_buttons()) buttonsTick = tick;
    lock(rowsLock);
    drawnThisTick = 0;
    unlock(rowsLock);
    if (tick % SAMPLE_FRAMES != 0) return unlock(polling);

    static Row batch[MAX_ROWS];
    static Machine states[MACHINES];
    static unsigned sequence = 0;
    lock(rowsLock);
    const unsigned n = rowCount;
    const unsigned lost = __atomic_exchange_n(&dropped, 0u, __ATOMIC_RELAXED);
    std::memcpy(batch, rows, n * sizeof(Row));
    rowCount = 0;
    unlock(rowsLock);
    lock(machinesLock);
    std::memcpy(states, machines, sizeof(states));
    unlock(machinesLock);

    outLength = 0;
    put("BEGIN,%u,%u,%u,%u\n", ++sequence, tick, n, lost);
    for (unsigned i = 0; i < n; ++i) {
        const Row& r = batch[i];
        put("TEXT,%u,%u,%llx,%.2f,%.2f,%.4f,%u,", r.tick, r.order, (unsigned long long)r.root,
            r.x, r.y, r.scale, r.encoding);
        putName(r.name);
        put(",");
        for (unsigned d = r.depth; d-- > 0;) {  // root first
            putName(r.path[d]);
            put("/");
        }
        put(",");
        putHex(r.text, r.bytes);
        put(",%u\n", r.length);
    }
    if (focusPath[0]) put("FOCUS,%s,%d,%u\n", focusPath, focusInput(), focusTick);
    put("INPUT,%u,%u\n", inputOnTick, inputOffTick);
    put("PAD,%llx,%u\n", (unsigned long long)tas::seen_buttons(), buttonsTick);
    for (const auto& m : states) {
        if (!m.machine) continue;
        const char* name = m.state >= 0 && m.state < m.count ? m.names[m.state] : nullptr;
        put("STATE,%llx,%u,%u,%u,%d,%.48s,", (unsigned long long)m.machine, m.executed, m.changed, m.appeared,
            m.frames, name ? name : "");
        // All its state names, which say what screen it is.
        for (int32_t i = 0; i < m.count; ++i) put(i ? "|%.48s" : "%.48s", m.names[i] ? m.names[i] : "");
        put("\n");
    }
    if (tilesSeen) {
        put("SLOTS");
        for (auto slot : tileSlot) put(",%d", slot);
        put("\n");
    }
    put("END,%u\n", sequence);
    writeScreen();
    unlock(polling);
}
}  // namespace smm2::ui_probe
