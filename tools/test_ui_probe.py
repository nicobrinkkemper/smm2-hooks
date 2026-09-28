import unittest
import struct
from ui_probe import decode_row, parse_samples, read_log, screen

def row(text="日本語🎵", encoding=0, length=None):
    raw=text.encode("utf-8" if encoding else "utf-16-le")
    n=len(raw)//(1 if encoding else 2) if length is None else length
    parent=(b"P_Parent"+bytes(16)).hex(); root=(b"RootPane"+bytes(16)).hex()
    return (f"TEXT,80000000,{encoding},{n},{n+1},129,255,"+(b"T_Test"+bytes(18)).hex()+","+raw[:256].hex()
        +f",7,0,90000000,{parent}/{root},"+bytes(0x60).hex())

class UiProbeTests(unittest.TestCase):
    def test_unicode(self):
        for encoding in [0,1]: self.assertEqual(decode_row(row(encoding=encoding))["text"],"日本語🎵")
    def test_path_is_root_first(self):
        self.assertEqual(decode_row(row())["path"],"RootPane/P_Parent")
    def test_screen_drops_offscreen_and_marks_focus(self):
        def g(x,y,s): f=[0.0]*24; f[16]=f[21]=s; f[19]=x; f[23]=y; return f
        rows=[dict(decode_row(row()),geom=g(0,0,1.03),order=5,root="0xa"),
              dict(decode_row(row()),geom=g(0,-500,1.0),order=6,root="0xa"),
              dict(decode_row(row()),geom=g(10,0,1.0),order=1,root="0xb"),
              dict(decode_row(row()),geom=g(20,0,1.0),order=7,root="0xc"),
              dict(decode_row(row()),geom=g(30,0,1.0),order=0,tick=6)]
        view=screen({"rows":rows})
        self.assertEqual(len(view["rows"]),3); self.assertEqual(view["focused"]["x"],0)
        self.assertEqual([r["x"] for r in view["active"]],[0,20])
    def test_focused_tile_maps_to_its_slot(self):
        f=[0.0]*24; f[16]=f[21]=1.05
        r=dict(decode_row(row()),geom=f,order=0,root="0xa",
               path="L_CourseDataList_02/N_All_00/N_Btn_00/L_CourseBtn_01/N_Cursor_00")
        slots=list(range(100,120))
        self.assertEqual(screen({"rows":[r],"slots":slots})["course_slot"],109)
        self.assertIsNone(screen({"rows":[r]})["course_slot"])
    def test_truncation(self):
        self.assertTrue(decode_row(row("A"*200))["truncated"])
    def test_tag_is_preserved_not_invented(self):
        decoded=decode_row(row("A\x0eB")); self.assertTrue(decoded["contains_controls"])
        self.assertEqual(decoded["text"],"A\x0eB");self.assertIsNone(decoded["focus"])
    def test_rejects_bad_lengths(self):
        with self.assertRaises(ValueError):decode_row(row("A",length=2))
    def test_only_complete_samples(self):
        text="BEGIN,1,1,0,0,7\n"+row()+"\nEND,1\nBEGIN,2,1,0,0,9\n"+row("New")
        samples,errors,partial=parse_samples(text)
        self.assertEqual(len(samples),1);self.assertTrue(partial);self.assertFalse(errors)
    def test_mismatched_footer(self):
        samples,errors,_=parse_samples("BEGIN,1,1,0,0,7\n"+row()+"\nEND,2")
        self.assertFalse(samples);self.assertTrue(errors)
    def test_missing(self):self.assertEqual(read_log("/definitely/missing/ui-probe.log")["status"],"unavailable")
if __name__=="__main__":unittest.main()
