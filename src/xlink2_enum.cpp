#include "smm2/log.h"
#include "hk/hook/Trampoline.h"

// xlink2::EnumPropertyDefinition::EnumPropertyDefinition(const char*, int, sead::Heap*, bool)
// sub_710059D9E0 — constructor, x0=this, x1=name, w2=count, x3=heap, w4=bool
//
// xlink2::EnumPropertyDefinition::entry(int, const char*)
// sub_710059DDA0 — adds enum value, x0=this, w1=index, x2=name

namespace smm2 {
namespace xlink2_enum {

static log::Logger s_log;
static bool s_inited = false;
static const char* s_current_enum = nullptr;

// Hook the constructor to capture enum type name
static HkTrampoline<void, void*, const char*, int, void*, bool> ctor_hook =
    hk::hook::trampoline([](void* self, const char* name, int count, void* heap, bool b) {
        if (!s_inited) {
            s_log.init("xlink2_enums.csv");
            s_log.write("enum_name,index,value_name\n", 27);
            s_inited = true;
        }
        s_current_enum = name;
        ctor_hook.orig(self, name, count, heap, b);
    });

// Hook entry() to capture each enum value
static HkTrampoline<void, void*, int, const char*> entry_hook =
    hk::hook::trampoline([](void* self, int index, const char* name) {
        if (s_inited && name) {
            const char* enum_name = s_current_enum ? s_current_enum : "?";
            s_log.writef("%s,%d,%s\n", enum_name, index, name);
        }
        entry_hook.orig(self, index, name);
    });

void init() {
    ctor_hook.installAtSym<"xlink2_EnumPropertyDefinition_ctor">();
    entry_hook.installAtSym<"xlink2_EnumPropertyDefinition_entry">();
    s_log.init("xlink2_enums.csv");
    s_log.write("enum_name,index,value_name\n", 27);
    s_inited = true;
}

void flush() {
    if (s_inited) s_log.flush();
}

} // namespace xlink2_enum
} // namespace smm2
