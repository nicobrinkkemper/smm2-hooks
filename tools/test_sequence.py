"""Game.sequence: steps close on the live status, and the pad is released."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import smm2  # noqa: E402


class FakeGame(smm2.Game):
    """Status advances one frame per read; x grows while RIGHT is held."""

    def __init__(self):
        self.writes, self.frame, self.x, self.mask = [], 0, 0.0, 0

    def _write_input(self, buttons=0, lx=0, ly=0):
        self.mask = buttons
        self.writes.append(buttons)

    def status(self, allow_stale=False):
        self.frame += 1
        if self.mask & smm2.BTN["RIGHT"]:
            self.x += 1.5
        return {"frame": self.frame, "x": self.x, "state": 3 if self.mask & smm2.BTN["A"] else 1,
                "scene_mode": 5, "powerup": 0, "y": 80.0}


class Sequence(unittest.TestCase):
    def test_parse_until(self):
        self.assertEqual(smm2.parse_until("x>=134 & state==62"), [("x", ">=", 134.0), ("state", "==", 62.0)])
        self.assertEqual(smm2.parse_until(""), [])
        with self.assertRaises(ValueError):
            smm2.parse_until("x=>1")

    def test_steps_end_on_their_condition(self):
        g = FakeGame()
        rows = g.sequence([{"buttons": "RIGHT", "until": "x>=30", "max_s": 5},
                           {"buttons": "A+RIGHT", "until": "state==3", "max_s": 5}])
        self.assertEqual([r["ended"] for r in rows], ["hit", "hit"])
        self.assertGreaterEqual(rows[0]["x"], 30)
        self.assertEqual(g.writes[-1], 0)   # the pad is let go at the end

    def test_a_step_without_until_holds_for_max_s(self):
        g = FakeGame()
        rows = g.sequence([{"buttons": "", "max_s": 0.05}])
        self.assertEqual(rows[0]["ended"], "time")
        self.assertGreaterEqual(rows[0]["t"], 0.05)

    def test_bad_condition_presses_nothing(self):
        g = FakeGame()
        with self.assertRaises(ValueError):
            g.sequence([{"buttons": "RIGHT", "until": "x>=1"}, {"buttons": "A", "until": "bad"}])
        self.assertEqual(g.writes, [])


if __name__ == "__main__":
    unittest.main()
