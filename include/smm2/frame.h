#pragma once

#include <cstdint>

namespace smm2 {
namespace frame {

using callback_t = void(*)(uint32_t frame);

// Hook procFrame_ and call cb every frame
void init(callback_t cb);

// Current frame counter
uint32_t current();

} // namespace frame
} // namespace smm2
