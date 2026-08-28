"""Regression tests for parse_course: object ids, sizes, and map markers.

    python3 -m unittest tools/test_parse_course.py   (from the repo root)
"""
import io
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.argv, _argv = ['x'], sys.argv
import gen_test_levels as gen  # noqa: E402
import parse_course as pc  # noqa: E402
sys.argv = _argv

VALID_LEVEL = os.path.join(HERE, '..', 'data', 'valid_test_level.bcd')


def parse_built(builder):
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, 'course_data_000.bcd')
        with open(path, 'wb') as f:
            f.write(gen.encrypt_course(builder().build()))
        return pc.parse_course(pc.decrypt_course(path))


def render(actors, tiles=()):
    out = io.StringIO()
    with redirect_stdout(out):
        pc.render_map({'actors': actors, 'tiles': list(tiles)})
    return out.getvalue()


def actor(type_id, x, y):
    return {'type': type_id, 'name': pc.ACTOR_NAMES[type_id], 'x': x, 'y': y, 'w': 1, 'h': 1, 'flags': 0}


class ObjectIds(unittest.TestCase):
    def test_table_is_contiguous(self):
        self.assertEqual(sorted(pc.ACTOR_NAMES), list(range(133)))

    def test_known_ids(self):
        for type_id, name in [(0, 'Goomba'), (8, 'Coin'), (20, 'SuperMushroom'), (23, 'NoteBlock'),
                              (27, 'Goal'), (59, 'Track'), (69, 'Player'), (91, 'Seesaw'), (132, 'OnOffTrampoline')]:
            self.assertEqual(pc.ACTOR_NAMES[type_id], name)
        self.assertEqual(gen.OBJ_NOTE_BLOCK, 23)
        self.assertEqual(gen.OBJ_MUSHROOM, 20)


class Parsing(unittest.TestCase):
    def test_generated_note_block(self):
        _, builder = gen.TEST_LEVELS[10]  # Track Note
        area = parse_built(builder)['overworld']
        notes = [a for a in area['actors'] if a['name'] == 'NoteBlock']
        self.assertEqual(len(notes), 1)
        self.assertEqual((notes[0]['w'], notes[0]['h']), (1, 1))
        self.assertTrue(notes[0]['flags'] & gen.FLAG_ON_TRACK)

    def test_generated_names_match_builder_ids(self):
        _, builder = gen.TEST_LEVELS[1]  # Jump Platforms
        area = parse_built(builder)['overworld']
        for a in area['actors']:
            self.assertEqual(a['name'], pc.ACTOR_NAMES[a['type']])
            self.assertNotIn('unk_', a['name'])

    @unittest.skipUnless(os.path.exists(VALID_LEVEL), 'data/valid_test_level.bcd missing')
    def test_valid_test_level(self):
        course = pc.parse_course(pc.decrypt_course(VALID_LEVEL))
        self.assertTrue(course['header']['name'])
        for a in course['overworld']['actors']:
            self.assertGreaterEqual(a['w'], 1)
            self.assertGreaterEqual(a['h'], 1)


class Rendering(unittest.TestCase):
    ACTORS = [actor(27, 16, 16), actor(69, 48, 16), actor(8, 80, 16), actor(91, 112, 16),
              actor(25, 144, 16), actor(30, 176, 16), actor(34, 208, 16), actor(16, 240, 16)]

    def test_tile_path_markers(self):
        out = render(self.ACTORS, tiles=[{'x': 0, 'y': 0, 'id': 0}, {'x': 16, 'y': 0, 'id': 0}])
        row = [l for l in out.splitlines() if l.startswith(' 1|')][0][3:]
        self.assertEqual(row[1], 'G')   # Goal
        self.assertEqual(row[3], 'M')   # Player
        self.assertEqual(row[5], 'c')   # Coin
        self.assertEqual(row[7], '*')   # Seesaw: no marker
        self.assertEqual(row[9], '*')   # Spiny: no marker
        self.assertEqual(row[11], '*')  # Lakitu: no marker
        self.assertEqual(row[13], '*')  # FireFlower: no marker
        self.assertEqual(row[15], '-')  # SemisolidPlatform

    def test_actor_only_path_markers(self):
        out = render(self.ACTORS)
        line = [l for l in out.splitlines() if 'G' in l][0]
        self.assertEqual(''.join(ch for ch in line if ch != ' '), 'GMc####-')


if __name__ == '__main__':
    unittest.main()
