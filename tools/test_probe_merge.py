"""merge_presets: presets that hook one function share the hook."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import probe  # noqa: E402


class MergePresets(unittest.TestCase):
    def merged(self, *keys):
        return probe.parse_config(probe.merge_presets(list(keys)))

    def test_one_hook_per_address(self):
        for keys in (("camera", "note"), ("rail", "note"), ("enemywalk", "player"), ("bgpass", "enemywalk")):
            hooks, _ = self.merged(*keys)
            addrs = [h["vaddr"] for h in hooks]
            self.assertEqual(len(addrs), len(set(addrs)), keys)

    def test_camera_and_note_share_the_player_hook(self):
        hooks, fields = self.merged("camera", "note")
        self.assertEqual([h["name"] for h in hooks if h["vaddr"] == 0x71015D3CC0], ["cam"])
        cam = {f["label"] for f in fields if f["hook"] == "cam"}
        self.assertTrue({"left", "bottom", "pos_x", "pos_y"} <= cam)   # same pos_x read is kept once
        self.assertIn("st_e", cam)   # the same u32 at +0x400 in both presets

    def test_identical_reads_kept_once(self):
        _, fields = self.merged("rail", "note")
        reads = [(f["hook"], f["type"], f["path"]) for f in fields]
        self.assertEqual(len(reads), len(set(reads)))

    def test_clashing_label_is_renamed(self):
        _, fields = self.merged("rail", "note")
        labels = [(f["hook"], f["label"]) for f in fields]
        self.assertEqual(len(labels), len(set(labels)))

    def test_single_preset_is_unchanged(self):
        for key in ("rail", "camera", "enemywalk"):
            a, b = probe.parse_config(probe.PRESETS[key]), self.merged(key)
            self.assertEqual([(h["name"], h["vaddr"]) for h in a[0]], [(h["name"], h["vaddr"]) for h in b[0]])
            self.assertEqual([(f["hook"], f["label"], f["type"], f["path"]) for f in a[1]],
                             [(f["hook"], f["label"], f["type"], f["path"]) for f in b[1]])


if __name__ == "__main__":
    unittest.main()
