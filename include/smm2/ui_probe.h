#pragma once
namespace smm2::ui_probe {
// Menu text, focus and screen state to sd:/smm2-hooks/ui-screen.txt, when
// sd:/smm2-hooks/ui-probe.txt says "capture". v3.0.3 only; docs/ui-probe.md.
void init();
void poll();  // once per frame
}
