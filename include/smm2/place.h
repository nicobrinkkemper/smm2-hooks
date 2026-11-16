#pragma once

#include <cstdint>

namespace smm2 { namespace place {

void init();
void per_frame(uint32_t frame);
// "<x> <y> <n>": hold the player at (x, y) for n frames. at_player: start
// with the first player seen in play (boot.txt) instead of now (ctl.txt).
bool parse(const char* args, bool at_player);

}}  // namespace smm2::place
