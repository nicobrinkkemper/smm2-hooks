#pragma once

#include <cstdint>

namespace nn {
    namespace hid {
        constexpr uint64_t BUTTON_STICK_L = 0x10;
        constexpr uint64_t BUTTON_STICK_R = 0x20;
        constexpr uint64_t BUTTON_MINUS = 0x800;
        constexpr uint64_t BUTTON_PLUS = 0x400;
        constexpr uint64_t BUTTON_LEFT = 0x1000;
        constexpr uint64_t BUTTON_UP = 0x2000;
        constexpr uint64_t BUTTON_RIGHT = 0x4000;
        constexpr uint64_t BUTTON_DOWN = 0x8000;

        struct full_key_state {
            int64_t sample;
            uint64_t buttons;
            int32_t sl_x;
            int32_t sl_y;
            int32_t sr_x;
            int32_t sr_y;
            uint32_t attributes;
        };
    }
}
