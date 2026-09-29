# Tutorial: from a runtime value to a mod (the course theme)

The game offers ten course themes, ids 0 to 9. A theme installed in slot 10
has no button in the editor, so the only way to reach it is to put 10 where
the game keeps the theme. This tutorial walks the whole path on that
example:

1. read the value at runtime,
2. find the code that writes it,
3. try the change by hand in the debugger,
4. turn it into a mod that needs no debugger.

Every step below was run in Eden on v3.0.3 with the Coursebot course
"Castle Flat" (theme 2, Castle) in slot 18. Addresses are in
`functions.csv` space (`0x7100000000` + offset); at runtime the main module
sits somewhere else every launch.

## 1. Read it

The status block the mod writes every frame (`status.bin`,
`docs/status-system-spec.md`) already carries the theme at `0x3C`.
`src/status.cpp` reads it through a pointer chain known from cheat tables:

```
[[main+0x2A67B70]+0x28]+0x210    one byte: 0 Ground ... 9 Forest
```

`python3 mcp/ctl.py game_status` shows it as `"theme"`. That is all a
pointer chain tells you: where a value sits, not what it is or who puts it
there.

## 2. Find who writes it

A write watchpoint stops the game at the instruction that writes an
address, and a watchpoint is the tool here anyway: we know the data, not
the code. (On the Eden this was run with, v0.2.0-rc1, hardware breakpoints
do not insert: `hbreak` gives "Enabled packet Z1 (hardware-breakpoint) not
recognized by stub". Later Eden releases list GDB improvements; not tried.)
The byte does not exist until the chain does, so the script watches each
link in turn: the global, then the pointer
at `+0x28`, then the byte. Launch Eden with the stub on
(`python3 mcp/ctl.py eden_launch '{"gdb": true}'`; the game waits for the
debugger), then run the script with
`gdb-multiarch -nx -q -batch -x theme_watch.py`:

```python
import gdb, struct, re, subprocess
CTL = ["mcp/.venv/bin/python", "mcp/ctl.py"]
gdb.execute("set pagination off"); gdb.execute("set confirm off")
gdb.execute("target remote 172.19.32.1:6543")      # the Windows host's IP from WSL
gdb.execute("handle SIGTRAP nostop noprint nopass")
inf = gdb.selected_inferior()
rd = lambda a, f: struct.unpack("<" + f, bytes(inf.read_memory(a, struct.calcsize(f))))[0]

# The main module is listed as Slope.nss (the game's code name), not "main".
mods = re.findall(r"(0x[0-9a-f]+) - (0x[0-9a-f]+) (\S+)", gdb.execute("mon get info", to_string=True))
base = int([m for m in mods if m[2].startswith("Slope")][0][0], 16)
csv = lambda a: hex(0x7100000000 + a - base)
G = base + 0x2A67B70

wps = {}
def watch(name, expr):
    if name in wps: wps[name].delete()
    wps[name] = gdb.Breakpoint(expr, gdb.BP_WATCHPOINT, gdb.WP_WRITE)

watch("G", "*(unsigned long*)0x%x" % G)
obj = buf = 0
boot = None
while True:
    gdb.execute("continue", to_string=True)
    pc, lr = int(gdb.parse_and_eval("$pc")), int(gdb.parse_and_eval("$lr"))
    if rd(G, "Q") != obj:
        obj = rd(G, "Q"); watch("buf", "*(unsigned long*)0x%x" % (obj + 0x28)); continue
    if rd(obj + 0x28, "Q") != buf:
        buf = rd(obj + 0x28, "Q")
        if buf: watch("theme", "*(unsigned char*)0x%x" % (buf + 0x210))
        if boot is None:   # the chain exists: now load the course
            boot = subprocess.Popen(CTL + ["game_boot", '{"target": "coursebot", "slot": 18}'])
        continue
    print("theme", rd(buf + 0x210, "B"), "pc", hex(pc), "lr", csv(lr),
          "x0", hex(int(gdb.parse_and_eval("$x0"))), "x2", hex(int(gdb.parse_and_eval("$x2"))))
    break
```

What it printed while the course loaded:

```
theme 2 pc 0x83b9a960 lr 0x7100e3c34c x0 0x2119a78bb8 x2 0x5bde0
```

- `pc` is not in the main module (`Slope.nss` ends at `0x8363bfff`): it is
  the SDK's `memcpy`. The game copied the theme along with something else.
- `lr`, the return address, is in main: `0x7100E3C34C`, inside
  `sub_7100E3BA90` (look it up in `functions.csv`).
- `x2` is the bytes left to copy, and the pointer at `+0x28` was allocated
  with 0x5BFC0 bytes: the size of a decrypted course file.

So the "theme byte" is the course file's own theme field, in a copy of the
course the game keeps in memory.

## 3. Read the writer

From the decomp checkout,
`python3 tools/decompile.py 0x7100E3BA90 --backend ida` shows the end of
the function:

```c
memcpy_0(*(void **)(v3 + 40), *v10, 0x5C000u);   // v3 + 40 = obj + 0x28
```

0x5C000 bytes is the whole `.bcd` file, its 0x10-byte file header included
(`docs/level-modification.md`). The decrypted course keeps the main area's
theme at `0x200`, so in this copy it is at `0x10 + 0x200 = 0x210`. The
same function builds a blank course afterwards and sets that byte to 0
(`*(_BYTE *)(v31 + 528) = 0`, 528 = 0x210): the same field again.

## 4. Try it by hand

The watchpoint fires after the byte is written, and `memcpy` only moves
forward, so writing 10 right at the stop sticks. In the loop above:

```python
    v = rd(buf + 0x210, "B")
    if v == 2:
        inf.write_memory(buf + 0x210, bytes([10]))
```

`game_status` then reports theme 10, and the course plays at 60 FPS.

Three things that go wrong on the way:

- `finish` (run until the function returns) fails: without symbols GDB
  cannot find the caller's frame. Poking at the stop is enough here.
- When a batch GDB session exits it kills the game, and the stub cannot
  detach. To look at the result, keep GDB attached, for example by
  continuing on a watchpoint that never fires, then screenshot.
- Every stop freezes the game while GDB works. The course timer read 023
  instead of about 290 in that run; with the mod below it reads normally.

## 5. The mod

A trampoline replaces a function with yours, and yours can still call the
original. Here it runs the copy, then writes the byte.
`src/theme_override.cpp`:

```cpp
static int s_theme = -1;

static HkTrampoline<long, long, int, char> course_copy =
    hk::hook::trampoline([](long obj, int a2, char a3) -> long {
        const long ret = course_copy.orig(obj, a2, a3);
        uint8_t* course = *reinterpret_cast<uint8_t**>(obj + 0x28);
        if (course) course[0x210] = static_cast<uint8_t>(s_theme);
        return ret;
    });

void init() {
    // read sd:/smm2-hooks/theme.txt; no file, no hook
    ...
    course_copy.installAtSym<"CourseDataCopy">();
}
```

- The signature comes from IDA: `__int64 sub_7100E3BA90(__int64, int, char)`.
- `installAtSym` needs the address by name in `syms/main.sym`, as an
  offset into the main module:
  `CourseDataCopy = 0xE3BA90`.
- A trampoline copies the function's first instruction, which must not be
  PC-relative (`docs/probe.md`, "Rules"). Check it with a one-line probe
  config: `hook course_copy 0x7100E3BA90` in a file, then
  `python3 tools/probe.py check <file>`. Here it is `sub sp` (`d10743ff`),
  which is fine.
- `init()` is called from `hkMain()` in `src/main.cpp`.

Build and install:

```bash
cmake -B build -DCMAKE_BUILD_TYPE=Release -GNinja   # again after adding a .cpp: the sources are globbed
ninja -C build
cp build/exefs/subsdk4 build/exefs/main.npdm <Eden load dir>/01009B90006DC000/smm2-hooks/exefs/
printf '10\n' > <Eden sdmc>/smm2-hooks/theme.txt
```

`eden_state` names both directories (`mods_dir`, `sd_hooks_dir`). The mod
reads `theme.txt` once at boot, so relaunch the game after changing it.

## What it does

With Castle Flat (theme 2) in Coursebot play:

| `theme.txt` | status theme | what the course looks like |
|---|---|---|
| absent | 2 | Castle: grey stone, lava |
| `9` | 9 | Forest: trees, and the lava is Forest's poison |
| `10` | 10 | brown ground, a black sky with twinkling stars, no lava; runs at 60 FPS |

Theme 10 does not crash the game: without anything installed there, it
takes art from somewhere that is not the Castle's. A theme installed in slot
10 is what that id then loads.

Not covered and not tried:

- The hook changes every course the game loads through this function,
  including the editor's. Saving a course while the override is on was not
  tried; the change only lives in memory, so the file on disk stays as it
  was unless the game writes the modified copy back.
- Only the main area. The sub area's theme is the same field in the second
  area (decrypted offset `0x2E0E0`, so `+0x2E0F0` in this copy).
- The file's CRC (header `+0x08`) is not updated. The game did not check it
  on this load.
