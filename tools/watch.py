#!/usr/bin/env python3
"""Real-time status watcher. Shows position, mode, velocity, state every 0.5s."""
import struct, time, sys, os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / '.env')
SD = os.environ.get('RYUJINX_SD_PATH', '')
STATUS = os.path.join(SD, 'smm2-hooks', 'status.bin')

MODE_NAMES = {0: 'EDITOR', 1: 'PLAY', 2: 'GOAL_ANIM', 3: 'DEATH_ANIM'}

def read_status():
    with open(STATUS, 'rb') as f:
        data = f.read(64)
    frame, mode, state, powerup = struct.unpack_from('<IIII', data, 0)
    px, py = struct.unpack_from('<ff', data, 16)
    vx, vy = struct.unpack_from('<ff', data, 24)
    state_frames = struct.unpack_from('<I', data, 32)
    in_water, is_dead, is_goal, has_player = struct.unpack_from('<BBBB', data, 36)
    facing, gravity, buffered, polls = struct.unpack_from('<ffII', data, 40)
    return {
        'frame': frame, 'mode': mode, 'state': state, 'powerup': powerup,
        'x': px, 'y': py, 'vx': vx, 'vy': vy,
        'state_frames': state_frames, 'in_water': in_water,
        'is_dead': is_dead, 'is_goal': is_goal, 'has_player': has_player,
        'facing': facing, 'gravity': gravity, 'buffered': buffered, 'polls': polls,
    }

duration = float(sys.argv[1]) if len(sys.argv) > 1 else 10.0
interval = float(sys.argv[2]) if len(sys.argv) > 2 else 0.5
end = time.time() + duration
prev_polls = None

while time.time() < end:
    s = read_status()
    mode_name = MODE_NAMES.get(s['mode'], f"?{s['mode']}")
    flags = []
    if s['is_dead']: flags.append('DEAD')
    if s['is_goal']: flags.append('GOAL')
    if s['in_water']: flags.append('WATER')
    
    # Detect if inputs are being polled (play vs editor)
    polls_active = ''
    if prev_polls is not None:
        polls_active = ' INPUTS_ON' if s['polls'] > prev_polls else ' INPUTS_OFF'
    prev_polls = s['polls']
    
    flag_str = f" [{','.join(flags)}]" if flags else ''
    print(f"f={s['frame']:6d} {mode_name:10s}{polls_active} | st={s['state']:3d} pw={s['powerup']} "
          f"| x={s['x']:7.1f} y={s['y']:6.1f} | vx={s['vx']:6.2f} vy={s['vy']:6.2f} "
          f"| stf={s['state_frames']:4d} g={s['gravity']:5.1f}{flag_str}")
    time.sleep(interval)
