#pragma once

// Runtime-configured function probes: sd:/smm2-hooks/probe.txt names up to
// eight functions to hook and, per hook, fields to read from x0 after the
// call. Rows go to sd:/smm2-hooks/probe.log, beside one pad row per frame.
// Format: docs/probe.md.
#include <cstdint>
namespace smm2 {
namespace probe {

void init();
void flush();
// One row per frame of the pad the game saw (the human's buttons with any
// injection merged in): P,<frame>,<buttons hex>,<lx>,<ly>. Called from the
// npad hook; repeats within a frame are dropped.
void log_pad(uint64_t buttons, int32_t lx, int32_t ly);

} // namespace probe
} // namespace smm2
