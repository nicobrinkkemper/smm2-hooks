#pragma once

#include <cstdint>

namespace smm2 {
namespace tas {

// TAS (Tool-Assisted Script) playback via nn::hid hook.
// Reads a script file from sd:/smm2-hooks/tas.csv
// Format: frame,buttons,stick_lx,stick_ly
//
// buttons is a bitmask (hex or decimal):
//   A=0x01, B=0x02, X=0x04, Y=0x08,
//   L_STICK=0x10, R_STICK=0x20,
//   L=0x40, R=0x80,
//   ZL=0x100, ZR=0x200,
//   PLUS=0x400, MINUS=0x800,
//   LEFT=0x1000, UP=0x2000, RIGHT=0x4000, DOWN=0x8000
//
// stick values: -32768 to 32767 (0 = centered)
//
// The script is sparse — only specify frames where input changes.
// Between specified frames, the last input is held.
//
// Example script (run right, jump at frame 100, release at 120):
//   frame,buttons,stick_lx,stick_ly
//   0,0x4000,0,0
//   100,0x4001,0,0
//   120,0x4000,0,0
//   300,0,0,0

// Button constants matching nn::hid
namespace btn {
    constexpr uint64_t A       = 0x01;
    constexpr uint64_t B       = 0x02;
    constexpr uint64_t X       = 0x04;
    constexpr uint64_t Y       = 0x08;
    constexpr uint64_t LSTICK  = 0x10;
    constexpr uint64_t RSTICK  = 0x20;
    constexpr uint64_t L       = 0x40;
    constexpr uint64_t R       = 0x80;
    constexpr uint64_t ZL      = 0x100;
    constexpr uint64_t ZR      = 0x200;
    constexpr uint64_t PLUS    = 0x400;
    constexpr uint64_t MINUS   = 0x800;
    constexpr uint64_t LEFT    = 0x1000;
    constexpr uint64_t UP      = 0x2000;
    constexpr uint64_t RIGHT   = 0x4000;
    constexpr uint64_t DOWN    = 0x8000;
}

void init();
uint32_t input_poll_count();

} // namespace tas
} // namespace smm2
