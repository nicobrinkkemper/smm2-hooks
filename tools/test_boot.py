#!/usr/bin/env python3
"""Tests for automate.py boot utilities.

Run: python3 tools/test_boot.py [--eden]

Tests the core functions used by the boot command without requiring
a running emulator (unit tests) plus optional integration tests.
"""

import os
import sys
import struct
import tempfile
import time

# Save flags before automate consumes sys.argv
_run_eden = '--eden' in sys.argv
_run_ryujinx = '--ryujinx' in sys.argv

# Add tools dir to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

passed = 0
failed = 0


def test(name, condition, detail=""):
    global passed, failed
    if condition:
        print(f"  ✅ {name}")
        passed += 1
    else:
        print(f"  ❌ {name}: {detail}")
        failed += 1


def make_status_bin(frame=100, state=1, has_player=1, pos_x=72.0, pos_y=32.0,
                    theme=7, real_phase=1, **kwargs):
    """Create a valid 68-byte status.bin."""
    blk = bytearray(68)
    struct.pack_into('<I', blk, 0, frame)       # frame
    struct.pack_into('<i', blk, 4, 0)           # game_phase
    struct.pack_into('<I', blk, 8, state)       # player_state
    struct.pack_into('<I', blk, 12, 0)          # powerup
    struct.pack_into('<f', blk, 16, pos_x)      # pos_x
    struct.pack_into('<f', blk, 20, pos_y)      # pos_y
    struct.pack_into('<f', blk, 24, 0.0)        # vel_x
    struct.pack_into('<f', blk, 28, 0.0)        # vel_y
    struct.pack_into('<I', blk, 32, 0)          # state_frames
    blk[36] = 0                                 # in_water
    blk[37] = 0                                 # is_dead
    blk[38] = 0                                 # is_goal
    blk[39] = has_player                        # has_player
    struct.pack_into('<f', blk, 40, 1.0)        # facing
    struct.pack_into('<f', blk, 44, -4.0)       # gravity
    struct.pack_into('<I', blk, 48, 0)          # buffered_action
    struct.pack_into('<I', blk, 52, frame)      # polls
    struct.pack_into('<i', blk, 56, real_phase) # real_game_phase
    blk[60] = theme                             # course_theme
    struct.pack_into('<I', blk, 64, 0)          # game_style
    return bytes(blk)


# ============================================================
# Unit Tests (no emulator needed)
# ============================================================

print("\n=== Unit Tests ===\n")

# Test 1: status.bin parsing
print("--- read_status ---")
with tempfile.TemporaryDirectory() as tmpdir:
    status_path = os.path.join(tmpdir, "status.bin")
    
    # Write a fake status.bin
    data = make_status_bin(frame=500, state=3, has_player=1, pos_x=150.0, pos_y=64.0, theme=2)
    with open(status_path, 'wb') as f:
        f.write(data)
    
    # Temporarily override SD_BASE
    import automate
    old_sd = automate.SD_BASE
    automate.SD_BASE = tmpdir
    
    s = automate.read_status()
    test("read_status returns dict", s is not None)
    test("frame=500", s and s['frame'] == 500, f"got {s.get('frame') if s else None}")
    test("state=3 (Jump)", s and s['player_state'] == 3, f"got {s.get('player_state') if s else None}")
    test("has_player=1", s and s.get('has_player') == 1)
    test("pos_x=150.0", s and abs(s['pos_x'] - 150.0) < 0.1)
    test("pos_y=64.0", s and abs(s['pos_y'] - 64.0) < 0.1)
    
    # Test no file
    os.remove(status_path)
    s = automate.read_status()
    test("read_status returns None when no file", s is None)
    
    automate.SD_BASE = old_sd

# Test 2: detect_state
print("\n--- detect_state ---")
with tempfile.TemporaryDirectory() as tmpdir:
    status_path = os.path.join(tmpdir, "status.bin")
    automate.SD_BASE = tmpdir
    automate._STATE_FILE = os.path.join(tmpdir, "nav_state.txt")
    
    # Editor state (43) — NOTE: editor might show state 1 on Eden, but 43 on Ryujinx
    data = make_status_bin(state=43, has_player=1)
    with open(status_path, 'wb') as f:
        f.write(data)
    state = automate.detect_state()
    test("state 43 → editor", state == "editor", f"got {state}")
    
    # Playing state (1) with nav_state=playing
    data = make_status_bin(state=1, has_player=1)
    with open(status_path, 'wb') as f:
        f.write(data)
    automate._save_state("playing")
    state = automate.detect_state()
    test("state 1 + nav=playing → playing", state == "playing", f"got {state}")
    
    # No player
    data = make_status_bin(state=0, has_player=0)
    with open(status_path, 'wb') as f:
        f.write(data)
    automate._save_state("main_menu")
    state = automate.detect_state()
    test("no player + nav=main_menu → main_menu", state == "main_menu", f"got {state}")
    
    # Loading
    data = make_status_bin(state=0, has_player=0, real_phase=-1)
    with open(status_path, 'wb') as f:
        f.write(data)
    state = automate.detect_state()
    test("real_phase=-1 → unknown (loading)", state == "unknown", f"got {state}")
    
    automate.SD_BASE = old_sd

# Test 2b: wait_for_change
print("\n--- wait_for_change ---")
with tempfile.TemporaryDirectory() as tmpdir:
    status_path = os.path.join(tmpdir, "status.bin")
    automate.SD_BASE = tmpdir
    
    data = make_status_bin(frame=100, state=1)
    with open(status_path, 'wb') as f:
        f.write(data)
    
    # Should timeout (value doesn't change)
    result = automate.wait_for_change('player_state', timeout_s=0.3, initial=1)
    test("wait_for_change timeout when no change", result is None)
    
    # Write different state, should detect
    data = make_status_bin(frame=101, state=5)
    with open(status_path, 'wb') as f:
        f.write(data)
    result = automate.wait_for_change('player_state', timeout_s=0.5, initial=1)
    test("wait_for_change detects change", result is not None and result['player_state'] == 5)
    
    automate.SD_BASE = old_sd

# Test 2c: is_fresh
print("\n--- is_fresh ---")
with tempfile.TemporaryDirectory() as tmpdir:
    status_path = os.path.join(tmpdir, "status.bin")
    automate.SD_BASE = tmpdir
    
    data = make_status_bin(frame=100)
    with open(status_path, 'wb') as f:
        f.write(data)
    
    # Frame doesn't advance → stale
    result = automate.is_fresh(timeout_s=0.2)
    test("is_fresh=False when frame stuck", result == False)
    
    automate.SD_BASE = old_sd

# Test 3: button parsing
print("\n--- parse_buttons ---")
test("A = 0x01", automate.parse_buttons("A") == 0x01)
test("L,R = 0xC0", automate.parse_buttons("L,R") == 0xC0, f"got 0x{automate.parse_buttons('L,R'):x}")
test("ZL,ZR = 0x300", automate.parse_buttons("ZL,ZR") == 0x300)
test("A,B,RIGHT = 0x4003", automate.parse_buttons("A,B,RIGHT") == 0x4003,
     f"got 0x{automate.parse_buttons('A,B,RIGHT'):x}")

# Test 4: PID tracking
print("\n--- emu_session.is_running ---")
import emu_session
# With no PID file, should fall back to process scan (returns False if not running)
test("is_running returns bool", isinstance(emu_session.is_running("eden"), bool))

# Test 5: screenshot (no process = returns None)
print("\n--- screenshot ---")
import automate as _auto_ss
old_eden = _auto_ss._use_eden
_auto_ss._use_eden = True  # Force eden mode
result = _auto_ss.screenshot()  # Should fail gracefully (no eden running... or succeed if running)
test("screenshot returns path or None", result is None or isinstance(result, str))
_auto_ss._use_eden = old_eden

# Test 6: status.bin byte layout
print("\n--- status.bin layout ---")
data = make_status_bin(frame=1234, state=43, has_player=1, pos_x=100.0, pos_y=200.0, theme=5)
test("68 bytes", len(data) == 68)
test("frame at [0:4]", struct.unpack('<I', data[0:4])[0] == 1234)
test("state at [8:12]", struct.unpack('<I', data[8:12])[0] == 43)
test("pos_x at [16:20]", abs(struct.unpack('<f', data[16:20])[0] - 100.0) < 0.01)
test("pos_y at [20:24]", abs(struct.unpack('<f', data[20:24])[0] - 200.0) < 0.01)
test("has_player at [39]", data[39] == 1)
test("theme at [60]", data[60] == 5)


# ============================================================
# Integration Tests (requires --eden or --ryujinx flag)
# ============================================================

if _run_eden or _run_ryujinx:
    emu = 'eden' if _run_eden else 'ryujinx'
    print(f"\n=== Integration Tests ({emu}) ===\n")
    
    # Reset SD_BASE for real paths
    from dotenv import load_dotenv
    env_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '.env')
    if os.path.exists(env_path):
        load_dotenv(env_path)
    
    if emu == 'eden':
        automate.SD_BASE = os.environ.get('EDEN_SD_PATH', '')
        automate._use_eden = True
    
    print("--- is_running ---")
    running = emu_session.is_running(emu)
    test(f"{emu} is_running returns bool", isinstance(running, bool))
    print(f"  (currently {'running' if running else 'not running'})")
    
    if running:
        print("\n--- read_status (live) ---")
        automate.INPUT_BIN = os.path.join(automate.SD_BASE, "input.bin")
        s = automate.read_status()
        test("read_status returns data", s is not None)
        if s:
            test("frame > 0", s['frame'] > 0, f"frame={s['frame']}")
            test("polls tracking", s.get('input_polls', 0) > 0, f"polls={s.get('input_polls')}")
            print(f"  State: {s.get('player_state')}, HasPlayer: {s.get('has_player')}")
            print(f"  Pos: ({s.get('pos_x', 0):.1f}, {s.get('pos_y', 0):.1f})")
            print(f"  Frame: {s['frame']}, Phase: {s.get('real_game_phase')}")
        
        print("\n--- frame advance ---")
        s1 = automate.read_status()
        time.sleep(0.5)
        s2 = automate.read_status()
        if s1 and s2:
            test("frame advances", s2['frame'] > s1['frame'],
                 f"{s1['frame']} → {s2['frame']}")
    else:
        print(f"  Skipping live tests ({emu} not running)")

else:
    print("\n(Skip integration tests — run with --eden or --ryujinx)")


# ============================================================
# Summary
# ============================================================

print(f"\n{'='*40}")
print(f"Results: {passed} passed, {failed} failed")
if failed:
    sys.exit(1)
print("All tests passed! ✅")
