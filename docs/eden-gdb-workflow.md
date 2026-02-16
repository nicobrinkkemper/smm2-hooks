# Eden GDB Workflow

## Setup

1. **Launch Eden with GDB**: `python3 tools/emu_session.py launch eden --gdb`
2. **Wait for game to load** (title screen visible, ~15-20s)
3. **Start persistent GDB session**:
   ```bash
   tmux new-session -d -s eden-gdb
   tmux send-keys -t eden-gdb "gdb-multiarch -nx -ex 'target remote 172.19.32.1:6543' -ex 'set confirm off' -ex 'set pagination off'" Enter
   ```
4. **GDB pauses game on connect** — send `c` to continue
5. **Navigate to gameplay** before setting breakpoints

## Critical Rules

- **ONE persistent GDB session** via tmux (`eden-gdb`). Never use batch `-batch` connections — they crash Eden on reconnect.
- **Always continue after a breakpoint/watchpoint hit**: `c` in GDB. Game is frozen while stopped!
- **Don't set breakpoints during loading** — `changeState` fires on Prepare Thread during scene transitions and freezes everything.
- **Delete breakpoints before continuing** if you're done with them: `delete <num>`, then `c`.
- **Handle SIGTRAP**: Run `handle SIGTRAP nostop noprint pass` if getting spurious stops after deleting watchpoints.
- **ASLR**: Addresses change every launch. Must search for function byte patterns each session.

## Finding Functions (ASLR)

Eden has ASLR — addresses change every launch. Search for known byte patterns:

```
# changeState (StateMachine::changeState)
# Args: x0=StateMachine*, x1=state_id
# PlayerObject = x0 - 0x3F0
find /b 0x80800000, 0x82000000, 0xf6, 0x57, 0xbd, 0xa9, 0xf4, 0x4f, 0x01, 0xa9, 0xfd, 0x7b, 0x02, 0xa9, 0xfd, 0x83, 0x00, 0x91, 0x08, 0x08, 0x40, 0xb9, 0xf3, 0x03, 0x01, 0x2a

# procFrame_ (PlayerObject::procFrame_)
# Args: x0=PlayerObject*
find /b 0x80800000, 0x82000000, 0xf3, 0x0f, 0x1e, 0xf8, 0xfd, 0x7b, 0x01, 0xa9, 0xfd, 0x43, 0x00, 0x91, 0x08, 0x08, 0x49, 0x39
```

## Common Operations

### Get Player Object
```
break *<changeState_addr>
c
# Wait for hit on MainThread
p/x $x0              # StateMachine*
# PlayerObject = $x0 - 0x3F0
delete <breakpoint_num>
c                     # ← ALWAYS CONTINUE!
```

### Set Hardware Watchpoint
```
watch *<address>      # Write watchpoint (4 bytes)
rwatch *<address>     # Read watchpoint
awatch *<address>     # Access (read+write) watchpoint
c
# On hit: read $pc, backtrace with bt, inspect memory
# ALWAYS: delete + continue when done
```

### Read Player Fields
```
# Given PlayerObject at $player:
x/1wx ($player + 0x3F8)   # current_state
x/1wx ($player + 0x3FC)   # state_frames  
x/1fw ($player + 0x230)   # pos_x (float)
x/1fw ($player + 0x234)   # pos_y (float)
x/1wx ($player + 0x4A8)   # powerup_id
```

### Backtrace
```
bt                    # Full backtrace
p/x $x30              # Return address (caller)
```

## Interacting via tmux

```bash
# Send GDB command
tmux send-keys -t eden-gdb "command here" Enter

# Read output
tmux capture-pane -t eden-gdb -p | tail -N

# Interrupt running game
tmux send-keys -t eden-gdb C-c
```

## Cleanup

```bash
# Kill GDB session
tmux send-keys -t eden-gdb "quit" Enter
tmux kill-session -t eden-gdb

# Kill Eden
python3 tools/emu_session.py kill eden
```

## Key Addresses (per-session, examples)

These change with ASLR. Find them fresh each launch.

| Function | ELF offset | How to find |
|----------|-----------|-------------|
| changeState | 0x8b9320 | Byte pattern search |
| procFrame_ | 0x2abb50 | Byte pattern search |
| PlayerObject | varies | x0 - 0x3F0 at changeState hit |
| current_state | PlayerObject + 0x3F8 | |
| state_frames | PlayerObject + 0x3FC | |
| powerup_id | PlayerObject + 0x4A8 | |
