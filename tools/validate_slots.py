"""Let Coursebot judge courses: install them into slots, restart Eden, visit Coursebot, report who survived.

    python3 validate_slots.py SLOT=course.bcd[,thumb.btl,replay.dat] [SLOT=... up to 4 or more]

Each slot gets the .bcd, a valid course_thumb + course_replay (the given ones, else copied
from the first registered slot) and its used flag in save.dat. On its next visit Coursebot
deletes every used slot it rejects, so reading save.dat afterwards is the verdict. One run
costs about a minute and judges every slot in the plan at once.
"""
import os
import shutil
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, '..', 'mcp'))
argv, sys.argv = sys.argv[1:], ['x']
import eden  # noqa: E402
import save_dat  # noqa: E402
from smm2 import Game  # noqa: E402

COMPANIONS = ('course_data_{:03d}.bcd', 'course_thumb_{:03d}.btl', 'course_replay_{:03d}.dat')


def used_slots(sd):
    body = save_dat.decrypt(open(os.path.join(sd, 'save.dat'), 'rb').read())
    return [s for s, f in save_dat.records(body) if f]


def install(sd, plan):
    registered = used_slots(sd)
    body = bytearray(save_dat.decrypt(open(os.path.join(sd, 'save.dat'), 'rb').read()))
    for slot, files in plan.items():
        donor = next((s for s in registered if s != slot), None)
        for i, pattern in enumerate(COMPANIONS):
            src = files[i] if i < len(files) else (os.path.join(sd, pattern.format(donor)) if donor is not None else None)
            if src is None:
                sys.exit(f'slot {slot}: no companion files given and no registered slot to borrow from')
            shutil.copy(src, os.path.join(sd, pattern.format(slot)))
        body[save_dat.RECORDS + 8 * slot + 1] = 1
    save = os.path.join(sd, 'save.dat')
    if not os.path.exists(save + '.orig'):
        shutil.copy2(save, save + '.orig')
    open(save, 'wb').write(save_dat.encrypt(bytes(body)))


def visit_coursebot(g, t0):
    if not g.wait_for(lambda s: s['scene_mode'] == 6, timeout=60):
        sys.exit('no title screen')
    print(f'title t+{time.time() - t0:.0f}s', flush=True)
    time.sleep(5)  # inputs right after the title appears are dropped
    for _ in range(3):
        if g.to_editor():
            break
        time.sleep(3)
    else:
        sys.exit('no editor')
    print(f'editor t+{time.time() - t0:.0f}s', flush=True)
    g.press('B', 100); time.sleep(0.3)
    g.press('PLUS', 150); time.sleep(1.5)
    g.press('RIGHT', 100); time.sleep(0.3)
    g.press('A', 100)
    time.sleep(6)
    for _ in range(4):  # confirm any delete dialogs
        g.press('A', 100); time.sleep(1.5)
    time.sleep(2)


def main():
    plan = {int(a.split('=')[0]): a.split('=', 1)[1].split(',') for a in argv}
    if not plan:
        sys.exit(__doc__)
    P = eden.paths(); sd = P.save_dir
    install(sd, plan)
    print('installed', sorted(plan), 'used before:', used_slots(sd), flush=True)
    t0 = time.time()
    eden.kill(); eden.launch(P, False)
    visit_coursebot(Game('eden'), t0)
    after = used_slots(sd)
    print(f'coursebot visited t+{time.time() - t0:.0f}s used after:', after)
    for slot in sorted(plan):
        print(f'slot {slot}: {"ACCEPTED" if slot in after else "DELETED"}  {[os.path.basename(f) for f in plan[slot]]}')


if __name__ == '__main__':
    main()
