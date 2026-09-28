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
    logger.init("ui-probe.log");
    logger.write("UI_PROBE_BOOT\n", 14);
    logger.flush();
    nn::fs::FileHandle file;
    const auto openResult = nn::fs::OpenFile(&file, "sd:/smm2-hooks/ui-probe.txt", nn::fs::MODE_READ);
    logger.writef("CONFIG_OPEN,%u\n", openResult); logger.flush();
    if (openResult != 0) return;
    char config[256] = {};
    size_t size = 0;
    const auto rc = nn::fs::ReadFile(&size, file, 0, config, sizeof(config)-1);
    nn::fs::CloseFile(file);
    logger.writef("CONFIG_READ,%u,%u\n", rc, (unsigned)size); logger.flush();
    if (rc != 0 || !size || size >= sizeof(config)-1) return;
    if (std::strcmp(config, "capture\n") != 0 && std::strcmp(config, "capture") != 0) {
        char* line = std::strchr(config, '\n');
        if (!line || std::strncmp(config, "print=", 6) != 0) return;
        *line++ = 0;
        if (std::strncmp(line, "expect=", 7) != 0) return;
        char* end = std::strchr(line, '\n');
        if (end) *end = 0;
        if (!config[6] || std::strlen(config+6) >= sizeof(printPane)
            || !line[7] || std::strlen(line+7) >= sizeof(expected)) return;
        std::strcpy(printPane, config+6);
        std::strcpy(expected, line+7);
    }
    logger.init("ui-probe.log");
    logger.writef("UI_PROBE,3,303,draw_submission,mode=%s\n", printPane[0] ? "print" : "capture");
    auto result = draw.installAtOffset(hk::ro::getMainModule(), 0x4C38B0);
    // Hakkun aborts on installation failure when requested; explicitly report it here.
    if (result.failed()) {
        logger.write("INSTALL_FAILED\n", 15);
        logger.flush();
        return;
    }
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
    logger.writef("END,%u\n", sequence);
    logger.flush();
    __atomic_clear(&consumer, __ATOMIC_RELEASE);
}
}
