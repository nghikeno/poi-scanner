// Alert rules: APPROACHING, TOUCH, W / M COMPLETE, ZONE BROKEN.
'use strict';
const { atr, trend } = require('./zones.js');

const ENTRY_TF = { W: '4H', D: '1H', '4H': '15m', '1H': '5m' };
const NEAR = 0.5;            // "approaching" = within half an average 1H candle of the zone
const RESET = 3;             // a new visit starts after price moves 3x that far away
const COOLDOWN = 4 * 3600;   // the same zone is not announced again within 4 hours

const zid = (z) => `${z.tf}|${z.kind}|${z.t}`;
function dist(z, p) { return p > z.top ? p - z.top : p < z.bot ? z.bot - p : 0; }

// W (demand) / M (supply) at the zone on the entry timeframe, completed by the LAST closed entry candle.
// Swing = 1 candle left, 2 candles right. Both bottoms (tops) must form at the zone.
function wm(z, E, touchT, tol) {
  const s = E.findIndex(b => b[0] >= touchT - 3 * (E[1][0] - E[0][0]));
  if (s < 0 || E.length < 6) return null;
  const last = E.length - 1, d = z.kind;
  const low = i => d === 1 ? E[i][3] : -E[i][2], high = i => d === 1 ? E[i][2] : -E[i][3], close = i => d === 1 ? E[i][4] : -E[i][4];
  const atZone = i => d === 1 ? E[i][3] <= z.top + tol : E[i][2] >= z.bot - tol;
  const piv = [];
  for (let i = Math.max(s, 1); i <= last - 2; i++)
    if (low(i) < low(i - 1) && low(i) <= low(i + 1) && low(i) <= low(i + 2) && atZone(i)) piv.push(i);
  if (piv.length < 2) return null;
  const b2 = piv[piv.length - 1], b1 = piv[piv.length - 2];
  let neck = -Infinity, ni = -1; for (let i = b1 + 1; i < b2; i++) if (high(i) > neck) { neck = high(i); ni = i; }
  if (ni < 0) return null;
  if (!(close(last) > neck)) return null;                       // completed on this candle close...
  for (let i = b2 + 1; i < last; i++) if (close(i) > neck) return null;   // ...and not earlier
  let ext = Infinity; for (let i = s; i <= last; i++) ext = Math.min(ext, low(i));
  return { entry: E[last][4], stop: d === 1 ? ext : -ext, neck: d === 1 ? neck : -neck, b1: E[b1][0], b2: E[b2][0], at: E[last][0] };
}

// target = latest swing high (low) of the movement on the zone's own timeframe, else the nearest opposite zone
function target(z, Z, zones, entry) {
  const after = Z.filter(b => b[0] > z.t);
  let tp = z.kind === 1 ? Math.max(...after.map(b => b[2])) : Math.min(...after.map(b => b[3]));
  if (!isFinite(tp) || (z.kind === 1 ? tp <= entry : tp >= entry)) {
    const opp = zones.filter(y => y.kind === -z.kind && (z.kind === 1 ? y.bot > entry : y.top < entry));
    if (!opp.length) return null;
    tp = z.kind === 1 ? Math.min(...opp.map(y => y.bot)) : Math.max(...opp.map(y => y.top));
  }
  return tp;
}

// st = this symbol's saved state; returns list of {type, z, ...}
function check(bars, zones, st, now) {
  const ev = [];
  const live = bars.live; if (!live.length) return ev;
  const price = live[live.length - 1][4];
  const a1h = atr(bars['1H']); const near = NEAR * a1h;
  const since = st.lastRun || now - 600;
  const recent = live.filter(b => b[0] + 300 > since);           // 5m candles since the last check
  const hi = Math.max(...recent.map(b => b[2])), lo = Math.min(...recent.map(b => b[3]));
  const prev = st.zones || {}; const cur = {};
  for (const [id, s] of Object.entries(prev)) if (now - (s.seen || 0) < 3 * 86400) cur[id] = s;   // remember zones for 3 days
  const ids = new Set();
  for (const z of zones) {
    const id = zid(z); ids.add(id);
    const s = cur[id] || { near: false, touch: 0, wm: 0, last: 0 };
    const dNow = dist(z, price);
    const touched = lo <= z.top && hi >= z.bot;
    const quiet = now - (s.last || 0) < COOLDOWN;
    if (dNow > RESET * near) { s.near = false; s.touch = 0; s.wm = 0; }       // price left: the next visit is new
    if (!s.near && !touched && dNow > 0 && dNow <= near) { s.near = true; if (!quiet) { s.last = now; ev.push({ type: 'near', z, price, d: dNow }); } }
    if (!s.touch && touched) {
      s.near = true;
      const fb = recent.find(b => b[3] <= z.top && b[2] >= z.bot);
      s.touch = fb ? fb[0] : now;
      if (!quiet || !s.touchSent) { s.last = now; s.touchSent = true; ev.push({ type: 'touch', z, price }); }
    }
    if (dNow > RESET * near) s.touchSent = false;
    if (s.touch && !s.wm) {
      const E = bars[ENTRY_TF[z.tf]];
      if (E && E.length > 20) {
        const r = wm(z, E, s.touch, 0.25 * atr(E));
        if (r) {
          s.wm = r.at;
          const tp = target(z, bars[z.tf], zones, r.entry);
          const risk = Math.abs(r.entry - r.stop);
          const rr = tp != null && risk ? Math.abs(tp - r.entry) / risk : null;
          if (rr != null && rr >= 1) ev.push({ type: 'wm', z, ...r, tp, rr, trend: trend(bars[z.tf]) });   // minimum 1R (hard rule)
        }
      }
    }
    cur[id] = { ...s, top: z.top, bot: z.bot, kind: z.kind, tf: z.tf, fl: z.fl, t: z.t, seen: now };
  }
  // fresh Weekly / Daily / 4H zones that disappeared because a candle closed through them
  for (const [id, s] of Object.entries(cur)) {
    if (ids.has(id) || s.broken || s.fl || s.tf === '1H' || s.seen !== st.lastRun) continue;
    const Z = bars[s.tf]; const c = Z && Z.length ? Z[Z.length - 1][4] : price;
    if ((s.kind === 1 && c < s.bot) || (s.kind === -1 && c > s.top)) { s.broken = true; ev.push({ type: 'broken', z: s, price: c }); }
  }
  st.zones = cur; st.lastRun = now;
  return ev;
}

module.exports = { check, ENTRY_TF };
