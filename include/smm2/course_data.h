#pragma once

#include <cstdint>

namespace smm2 {
namespace course_data {

// Hooks nn::fs::WriteFile to intercept BCD course data saves.
// When a write to a course_data_XXX.bcd path is detected, captures
// the buffer pointer and parses BCD header fields (theme, gamestyle, etc.)
void init();

// Returns the last-seen course theme (0-9), or 0xFF if not yet captured.
uint8_t theme();

// Returns the last-seen gamestyle raw value (0x314d=SMB1, etc.), or 0 if unknown.
uint16_t gamestyle();

// Returns the last-seen course name (UTF-16LE decoded to ASCII), or empty string.
const char* course_name();

} // namespace course_data
} // namespace smm2
