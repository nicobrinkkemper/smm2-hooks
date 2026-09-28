"""tools/ui_probe.py against hand-built snapshots in the mod's format."""
import unittest

from ui_probe import course_slot, menu_state, parse, read, readable, screen, under

GRID = "L_CourseDataList_02/N_All_00/N_Btn_00/L_CourseBtn_01/N_Cursor_00/"


def text_line(text="日本語🎵", name="T_Title_00", path=GRID, x=0.0, y=0.0, tick=60, order=0, root="a", length=None):
    raw = text.encode("utf-16-le")
    n = len(raw) // 2 if length is None else length
    return f"TEXT,{tick},{order},{root},{x:.2f},{y:.2f},1.0000,0,{name},{path},{raw.hex()},{n}"


def snapshot(*lines, sequence=7, tick=60):
    rows = sum(line.startswith("TEXT,") for line in lines)
    return "\n".join([f"BEGIN,{sequence},{tick},{rows},0", *lines, f"END,{sequence}"]) + "\n"


def state(machine, name, names, executed=60, frames=30):
    return f"STATE,{machine},{executed},{executed - frames},{frames},{name},{'|'.join(names)}"


LIST = ["cInit", "cIdle", "cAppear", "cDisp", "cOpenConfirmDelete", "cToPlay", "cDisappear"]
LOADER = ["cLoadWait", "cLoad", "cLoadEnd"]


class Parse(unittest.TestCase):
    def test_unicode_and_path(self):
        row = parse(snapshot(text_line()))["rows"][0]
        self.assertEqual(row["text"], "日本語🎵")
        self.assertEqual(row["path"], GRID + "T_Title_00")
        self.assertFalse(row["truncated"])

    def test_truncation_is_reported(self):
        self.assertTrue(parse(snapshot(text_line("A", length=200)))["rows"][0]["truncated"])

    def test_torn_snapshot_is_refused(self):
        with self.assertRaises(ValueError):
            parse(snapshot(text_line())[:-6])
        with self.assertRaises(ValueError):
            parse(snapshot(text_line()).replace("END,7", "END,6"))

    def test_mod_error_is_raised(self):
        with self.assertRaises(RuntimeError):
            parse("ERROR,hook install\n")

    def test_missing_file(self):
        self.assertEqual(read("/definitely/missing/ui-screen.txt")["status"], "unavailable")


class Screen(unittest.TestCase):
    def test_offscreen_and_older_rows_are_dropped(self):
        view = screen(parse(snapshot(text_line("on"), text_line("below", y=-500, order=1),
                                     text_line("earlier", tick=54, order=2))))
        self.assertEqual([r["text"] for r in view["rows"]], ["on"])

    def test_focus_is_the_game_path_topmost_first_layers_below_are_background(self):
        view = screen(parse(snapshot(
            text_line("grid", root="g", order=0),
            text_line("No", name="T_Btn_00", path="RootPane/N_Btn_00/L_BtnL_00/N_Cursor_00/", root="d", order=1),
            text_line("Yes", name="T_Btn_00", path="RootPane/N_Btn_00/L_BtnR_00/N_Cursor_00/", root="d", order=2),
            "FOCUS,/L_BtnR_00,1")))
        self.assertEqual(view["focused"]["text"], "Yes")
        self.assertIs(view["input"], True)
        self.assertEqual([r["text"] for r in view["active"]], ["No", "Yes"])

    def test_focus_left_from_an_earlier_screen_is_dropped(self):
        view = screen(parse(snapshot(text_line("PAUSE MENU", path="RootPane/N_All_00/"), "FOCUS,/L_Play_00,1")))
        self.assertIsNone(view["focus"])
        self.assertIsNone(view["focused"])

    def test_empty_tile_keeps_the_focus_and_its_slot(self):
        slots = ",".join(str(s) for s in [-1] * 8 + [4, -1, -1, -1] + [-1] * 8)
        view = screen(parse(snapshot(text_line("Flat", path="L_CourseDataList_02/N_All_00/L_CourseBtn_00/"),
                                     "FOCUS,/L_CourseDataList_02/L_CourseBtn_01,-1", "SLOTS," + slots)))
        self.assertIsNone(view["focused"])  # an empty tile draws no text
        self.assertEqual((view["course_slot"], view["course_slot_source"]), (5, "row"))

    def test_bound_slot(self):
        sample = parse(snapshot("SLOTS," + ",".join(str(100 + i) for i in range(20))))
        self.assertEqual(course_slot(sample, "/L_CourseDataList_02/L_CourseBtn_01"), (109, "bound"))
        self.assertEqual(course_slot(sample, "/L_Edit_00"), (None, None))

    def test_path_components_in_order(self):
        self.assertTrue(under(GRID + "T_Title_00", "/L_CourseDataList_02/L_CourseBtn_01"))
        self.assertFalse(under(GRID + "T_Title_00", "/L_CourseBtn_01/L_CourseDataList_02"))


class Ready(unittest.TestCase):
    def test_loading_holds_the_menus_up(self):
        menu = menu_state(parse(snapshot(state("aa", "cDisp", LIST), state("bb", "cLoad", LOADER))))
        self.assertFalse(menu["ready"])
        self.assertEqual(menu["transitions"], ["loader:Load"])

    def test_loaded_list_takes_input(self):
        menu = menu_state(parse(snapshot(state("aa", "cDisp", LIST), state("bb", "cLoadEnd", LOADER))))
        self.assertTrue(menu["ready"])
        self.assertIn("coursebot_list:Disp", [f'{s["screen"]}:{s["state"]}' for s in menu["screens"]])

    def test_a_dormant_machine_does_not_count(self):
        menu = menu_state(parse(snapshot(state("aa", "cDisp", LIST), state("bb", "cLoad", LOADER, executed=12))))
        self.assertTrue(menu["ready"])

    def test_screen_input_follows_the_switch_after_disp(self):
        before = parse(snapshot(state("aa", "cDisp", LIST, frames=2), "INPUT,50,57"))
        after = parse(snapshot(state("aa", "cDisp", LIST, frames=2), "INPUT,58,57"))
        self.assertFalse(menu_state(before)["screen_input"])
        self.assertTrue(menu_state(after)["screen_input"])

    def test_leaving_is_a_transition(self):
        self.assertFalse(menu_state(parse(snapshot(state("aa", "cToPlay", LIST))))["ready"])


class Glyphs(unittest.TestCase):
    def test_known_and_unknown(self):
        self.assertEqual(readable("Press  + "), "Press [L] + [R]")
        self.assertEqual(readable(" Select"), "[U+E0EA] Select")


if __name__ == "__main__":
    unittest.main()
