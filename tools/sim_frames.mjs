// smm2-sim frame by frame for tools/side_by_side.py (docs/frame-capture.md):
//   PLAYWRIGHT_FROM=<dir with node_modules/playwright> node tools/sim_frames.mjs <base url> <out dir> <count> <slot>
// Loads /level/slot-0/ (prerendered in a static build), switches to the slot, then tick(0) + canvas screenshot per frame.
import { createRequire } from "node:module";
const require = createRequire(`${process.env.PLAYWRIGHT_FROM || process.cwd()}/package.json`);
const { chromium } = require("playwright");
const [base, out, count, slot] = [process.argv[2], process.argv[3], +process.argv[4], +process.argv[5]];
const b = await chromium.launch();
const p = await b.newPage({ viewport: { width: 1280, height: 900 } });
const errors = []; p.on("pageerror", (e) => errors.push(String(e)));
await p.goto(base + "/level/slot-0/", { waitUntil: "load" });
await p.waitForFunction(() => window.__sim, { timeout: 30000 });
await p.waitForTimeout(1000);
await p.evaluate((s) => window.__sim.loadCourse(s), slot);
await p.waitForTimeout(1500);
const canvas = p.locator("canvas").first();
const paint = () => p.evaluate(() => new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r))));
const frame0 = await p.evaluate(() => window.__sim.getFrame());
for (let k = 0; k < count; k++) {
  await paint();
  await canvas.screenshot({ path: `${out}/${String(k).padStart(6, "0")}.png` });
  await p.evaluate(() => window.__sim.tick(0));
  if (k % 200 === 0) console.log("sim", k, await p.evaluate(() => window.__sim.getFrame()));
}
console.log(JSON.stringify({ frame0, end: await p.evaluate(() => window.__sim.getFrame()), errors }));
await b.close();
