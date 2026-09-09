#pragma once

// Runtime-configured function probes: sd:/smm2-hooks/probe.txt names up to
// eight functions to hook and, per hook, fields to read from x0 after the
// call. Rows go to sd:/smm2-hooks/probe.log. Format: docs/probe.md.
namespace smm2 {
namespace probe {

void init();
void flush();

} // namespace probe
} // namespace smm2
