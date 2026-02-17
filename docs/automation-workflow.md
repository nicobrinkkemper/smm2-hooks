# SMM2 Automation Workflow

## Boot Sequence (Fully Automated)

```
Launch Eden
    ↓
Loading (frame 0-200)
    ↓
Title Screen (frame ~200+)
    ↓
Wait for frame > 1000       ← Required! L+R doesn't work before this
    ↓
Hold L+R for 2 seconds      ← Skips title animation
    ↓
Wait 2.5 seconds
    ↓
Press A for 500ms           ← Enters Course Maker
    ↓
Editor (scene_mode=1)
    ↓
Press B (clear focus) + MINUS  ← Enter play mode
    ↓
Play Mode (scene_mode=5)    ← Full TAS control available
```

## Key Timings

| Step | Timing | Notes |
|------|--------|-------|
| Wait for title | frame > 1000 | L+R skip doesn't work earlier |
| L+R hold | 2000ms | Skips title screen animation |
| Wait after L+R | 2500ms | Let animation complete |
| A press | 500ms | Enter menu/Course Maker |

## Patches Applied

### Skip Intro Cutscene (`skip_intro.pchtxt`)
- Address: `017E432C`
- Change: `mov w1, #2` → `mov w1, #4`
- Effect: Skips intro cutscene, goes to phase 4 (but still shows title)
- nsobid: `C2DC405AC414C37C8B1C50219C7A0F0C`

## Code

### smm2.py - to_editor()
```python
def to_editor(self, timeout=45):
    # Wait for valid scene
    for _ in range(30):
        sc = self.scene()
        if sc in ('editor', 'play', 'title'):
            break
        time.sleep(0.5)
    
    if sc == 'editor':
        return True
    if sc == 'play':
        self.press('MINUS', 200)
        return self.wait_for(...)
    if sc == 'title':
        # Wait for frame > 1000
        for _ in range(30):
            s = self.status()
            if s and s['frame'] > 1000:
                break
            time.sleep(0.5)
        # L+R skip + A to enter
        self.hold('L+R', 2000)
        time.sleep(2.5)
        self.press('A', 500)
        return self.wait_for(...)
```

### boot_to_editor.py
```bash
python3 boot_to_editor.py eden         # → editor
python3 boot_to_editor.py eden --play  # → play mode
```

## What Does NOT Work

- Input injection at title with frame < 1000 (ignored)
- Skipping title screen entirely via patch (would need different patch)
