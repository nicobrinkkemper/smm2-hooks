# SMM2 Automation Workflow

## Boot Modes

### 1. Editor Demo (default)
```
Title → L+R → A → Editor (scene_mode=1)
```
Uses the hardcoded demo level from the editor.

### 2. Editor Play (`--play`)
```
Title → L+R → A → Editor → B+MINUS → Play (scene_mode=5)
```
Test-play the editor demo level.

### 3. Coursebot (`--slot N`)
```
Title → L+R → RIGHT → A → DOWN×3 → A → [wait 5s] → A → [wait 1s] → A → Play (scene_mode=7)
```
Play a saved course from Coursebot. Slot 0 = first course, 4 slots per row.

## Scene Modes

| Mode | Description |
|------|-------------|
| 0 | Loading/transition |
| 1 | Editor |
| 5 | Editor play (test-play) |
| 6 | Title/menu |
| 7 | Coursebot play (play-only) |

## Key Timings

| Step | Timing | Notes |
|------|--------|-------|
| Wait for title | frame > 400 | L+R doesn't work reliably earlier |
| L+R hold | 1500ms | Opens menu from title |
| Coursebot load | 5000ms | UI needs time to populate |
| Details slide | 1000ms | Animation after selecting course |
| A press | 150-200ms | Menu selections |

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
python3 boot_to_editor.py eden              # → editor (demo level)
python3 boot_to_editor.py eden --play       # → play mode (demo level)
python3 boot_to_editor.py eden --slot 0     # → play Coursebot slot 0
python3 boot_to_editor.py eden --slot 75    # → play Coursebot slot 75
python3 boot_to_editor.py eden --frame 600  # → custom frame threshold
```

Typical boot times:
- Editor: ~17s
- Editor play: ~18s  
- Coursebot play: ~30s

## What Does NOT Work

- Input injection at title with frame < 1000 (ignored)
- Skipping title screen entirely via patch (would need different patch)
