#pragma once
#include <cstdint>
namespace smm2::ui_probe {
// Experimental, opt-in, v3.0.3 only. Does not identify active menus or focus.
void init();
void poll();
}
