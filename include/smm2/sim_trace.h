#pragma once

#include <cstdint>

namespace smm2 {
namespace sim_trace {

void init();
void per_frame(uint32_t frame);
void flush();

} // namespace sim_trace
} // namespace smm2
