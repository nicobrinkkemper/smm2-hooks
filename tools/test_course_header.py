"""Generated courses keep the game's course header rules.

    python3 -m unittest tools/test_course_header.py   (from the repo root)

Every @test_level passes preflight, and a level that breaks one header rule
(CourseDataValidator::validate's error bits, smm2-decomp
docs/re-notes/course-validator.md) is refused with that rule's bit named.
"""
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.argv, _argv = ['x'], sys.argv
import gen_test_levels as gen  # noqa: E402
sys.argv = _argv


def flat(style='SMB1'):
    b = gen.LevelBuilder("x", style)
    b.add_ground_block(7, 24, y_surface=4, height=5)
    b.goal_y = 5
    return b


def breaking(change, style='SMB1'):
    b = flat(style)
    change(b)
    return b


def many_objects(b, n, **record):
    for _ in range(n):
        b.add_actor(gen.OBJ_COIN, 12, 10, **record)


def much_ground(b):
    b.width = 200
    b.add_ground_block(7, 199, y_surface=20, height=21)


def many_tracks(b):
    b.width = 60
    for _ in range(1501):
        b.add_track(10, 10, gen.TRACK_SHAPE_HORIZONTAL)


def set_attr(**kw):
    return lambda b: [setattr(b, k, v) for k, v in kw.items()]


BROKEN = [
    (0x400, 'start row 0', set_attr(start_y=0), 'SMB1'),
    (0x400, 'start row 26', set_attr(start_y=26), 'SMB1'),
    (0x400, 'start row 1 in 3D World', set_attr(start_y=1, goal_y=5), '3DW'),
    (0x800, 'goal row 16', set_attr(goal_y=16), 'SMB1'),
    (0x800, 'goal row 1 in 3D World', set_attr(goal_y=1), '3DW'),
    (0x2, 'sub area autoscroll 4', set_attr(sub_autoscroll=4), 'SMB1'),
    (0x4, 'sub area theme 10', set_attr(sub_theme=10), 'SMB1'),
    (0x4, 'night in 3D World', set_attr(area_flag=2), '3DW'),
    (0x8, 'vertical overworld', set_attr(vertical=True), 'SMB1'),
    (0x100, 'overworld 23 wide', set_attr(width=23), 'SMB1'),
    (0x100, 'overworld 28 tall', set_attr(height=28), 'SMB1'),
    (0x100, 'vertical sub area 84 wide', set_attr(sub_vertical=True), 'SMB1'),
    (0x100, 'vertical sub area 27 tall', set_attr(sub_vertical=True, sub_width=48), 'SMB1'),
    (0x10, 'liquid end over the top', set_attr(liquid=(26, 0, 0, 5)), 'SMB1'),
    (0x80, 'liquid start over the top', set_attr(liquid=(5, 0, 0, 26)), 'SMB1'),
    (0x20, 'liquid mode 3', set_attr(liquid=(5, 3, 0, 5)), 'SMB1'),
    (0x40, 'liquid speed 4', set_attr(liquid=(5, 0, 4, 5)), 'SMB1'),
    (0x8000, '2601 objects', lambda b: many_objects(b, 2601), 'SMB1'),
    (0x10000, '301 linked objects', lambda b: many_objects(b, 301, lid=0), 'SMB1'),
    (0x400000, '4053 ground tiles', much_ground, 'SMB1'),
    (0x800000, '1501 tracks', many_tracks, 'SMB1'),
]


class CourseHeader(unittest.TestCase):
    def test_every_level_passes(self):
        for slot, (name, builder) in sorted(gen.TEST_LEVELS.items()):
            with self.subTest(slot=slot, name=name):
                b = builder()
                b.preflight()
                self.assertEqual(gen.header_errors(b.build()), [])
        self.assertGreater(len(gen.TEST_LEVELS), 0)

    def test_the_base_level_passes(self):
        flat().preflight()
        flat('3DW').preflight()

    def test_each_broken_rule_is_refused(self):
        for bit, why, change, style in BROKEN:
            with self.subTest(rule=hex(bit), why=why):
                b = breaking(change, style)
                with self.assertRaisesRegex(ValueError, f"header rule {bit:#x} "):
                    b.preflight()
                with self.assertRaisesRegex(ValueError, f"header rule {bit:#x} "):
                    b.build()

    def test_a_broken_rule_names_only_itself(self):
        """The breaks above touch one rule each: no other header rule fires."""
        for bit, why, change, style in BROKEN:
            with self.subTest(rule=hex(bit), why=why):
                b = breaking(change, style)
                rules = {m.split(' (')[0] for m in gen.header_errors(b._write(bytearray(b.data)))}
                self.assertEqual(rules, {f"header rule {bit:#x}"})


if __name__ == '__main__':
    unittest.main()
