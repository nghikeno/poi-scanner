// POI structure zones - the same rules as the TradingView indicator "POI Zones & Trendlines".
// Bars: arrays [time(sec), open, high, low, close], CLOSED candles only, oldest first.
'use strict';

function atr(b, n = 14) {            // TradingView ta.atr (RMA of true range, seeded with an SMA)
  let r = null; const tr = [];
  for (let i = 0; i < b.length; i++) {
    const t = i === 0 ? b[i][2] - b[i][3]
      : Math.max(b[i][2] - b[i][3], Math.abs(b[i][2] - b[i - 1][4]), Math.abs(b[i][3] - b[i - 1][4]));
    tr.push(t);
    if (i === n - 1) r = tr.reduce((a, x) => a + x, 0) / n;
    else if (i >= n) r = (r * (n - 1) + t) / n;
  }
  return r;
}

// ext = true for the Weekly (newer zone = extreme of the whole latest movement)
// flips = true for 4H and 1H (broken swings now being retested)
function structureZones(b, { ext = false, flips = false, n = 2, minBars = 52 } = {}) {
  const NN = b.length;
  if (NN < minBars || NN <= 4 * n) return [];
  const a1 = atr(b);
  const H = i => b[i][2], L = i => b[i][3], C = i => b[i][4], O = i => b[i][1], T = i => b[i][0];
  let uh = [], ul = [], bkH = [], bkL = [], minH = null, maxL = null;
  let iU = -1, pU = -1, iD = -1, pD = -1;
  for (let i = 2 * n; i < NN; i++) {
    const c = C(i);
    if (minH !== null && c > minH) {
      iU = i; pU = -1; minH = null;
      for (let q = uh.length - 1; q >= 0; q--) {
        const pq = uh[q];
        if (H(pq) < c) {
          if (pU < 0) { pU = pq; bkH.push([pq, i]); if (bkH.length > 8) bkH.shift(); }
          uh.splice(q, 1);
        } else if (minH === null || H(pq) < minH) minH = H(pq);
      }
    }
    if (maxL !== null && c < maxL) {
      iD = i; pD = -1; maxL = null;
      for (let q = ul.length - 1; q >= 0; q--) {
        const pq = ul[q];
        if (L(pq) > c) {
          if (pD < 0) { pD = pq; bkL.push([pq, i]); if (bkL.length > 8) bkL.shift(); }
          ul.splice(q, 1);
        } else if (maxL === null || L(pq) > maxL) maxL = L(pq);
      }
    }
    const p = i - n; let sh = true, sl = true;
    for (let k = p - n; k <= p + n; k++) {
      if (k === p) continue;
      if (H(k) >= H(p)) sh = false;
      if (L(k) <= L(p)) sl = false;
    }
    if (sh) { uh.push(p); minH = minH === null ? H(p) : Math.min(minH, H(p)); }
    if (sl) { ul.push(p); maxL = maxL === null ? L(p) : Math.max(maxL, L(p)); }
  }
  let sI = -1, dI = -1;
  if (iU >= 2) for (let k = iU; k >= 2; k--) if (L(k) < L(k - 1) && L(k) < L(k - 2)) { dI = k; break; }
  if (iD >= 2) for (let k = iD; k >= 2; k--) if (H(k) > H(k - 1) && H(k) > H(k - 2)) { sI = k; break; }
  if (ext) {
    if (iD > iU && dI >= 0) { sI = dI; for (let k = dI; k <= iD; k++) if (H(k) > H(sI)) sI = k; }
    else if (iU > iD && sI >= 0) { dI = sI; for (let k = sI; k <= iU; k++) if (L(k) < L(dI)) dI = k; }
  }
  const bodyTop = k => Math.max(O(k), C(k)), bodyBot = k => Math.min(O(k), C(k));
  const out = [];
  if (sI >= 0) {
    const zt = H(sI), k0 = Math.max(sI - 1, 0), k1 = Math.min(sI + 1, NN - 1);
    const zb = Math.min(Math.max(bodyTop(k0), bodyTop(sI), bodyTop(k1)), zt - 0.05 * a1);
    let ok = true; for (let k = sI + 1; k < NN; k++) if (C(k) > zt + 0.25 * a1) ok = false;
    if (ok) out.push({ top: zt, bot: zb, kind: -1, t: T(sI), fl: false });
  }
  if (dI >= 0) {
    const zb = L(dI), k0 = Math.max(dI - 1, 0), k1 = Math.min(dI + 1, NN - 1);
    const zt = Math.max(Math.min(bodyBot(k0), bodyBot(dI), bodyBot(k1)), zb + 0.05 * a1);
    let ok = true; for (let k = dI + 1; k < NN; k++) if (C(k) < zb - 0.25 * a1) ok = false;
    if (ok) out.push({ top: zt, bot: zb, kind: 1, t: T(dI), fl: false });
  }
  if (flips) {
    const cl = C(NN - 1); const f = [];
    for (const side of [0, 1]) {
      const bk = side === 0 ? bkH : bkL; const kd = side === 0 ? 1 : -1;
      for (let q = bk.length - 1; q >= 0; q--) {
        const [pq, bi] = bk[q]; const k0 = Math.max(pq - 1, 0), k1 = Math.min(pq + 1, NN - 1);
        let zt, zb, ok;
        if (side === 0) {
          zt = H(pq); zb = Math.min(Math.max(bodyTop(k0), bodyTop(pq), bodyTop(k1)), zt - 0.05 * a1);
          ok = cl - zt <= 2 * a1;
          for (let k = bi; k < NN; k++) if (C(k) < zb - 0.25 * a1) ok = false;
        } else {
          zb = L(pq); zt = Math.max(Math.min(bodyBot(k0), bodyBot(pq), bodyBot(k1)), zb + 0.05 * a1);
          ok = zb - cl <= 2 * a1;
          for (let k = bi; k < NN; k++) if (C(k) > zt + 0.25 * a1) ok = false;
        }
        if (ok && f.some(z => z.kind === kd && z.top >= zb && z.bot <= zt)) ok = false;
        if (ok && out.some(z => z.kind === kd && z.top >= zb && z.bot <= zt)) ok = false;
        if (f.filter(z => z.kind === kd).length >= 2) ok = false;
        if (ok) { const z = { top: zt, bot: zb, kind: kd, t: T(pq), fl: true }; f.push(z); out.push(z); }
      }
    }
  }
  return out;
}

// trend of a timeframe, as in the indicator: last two swing highs and lows (2 candles each side)
function trend(b, n = 2) {
  const hi = [], lo = [];
  for (let p = n; p < b.length - n; p++) {
    let sh = true, sl = true;
    for (let k = p - n; k <= p + n; k++) { if (k === p) continue; if (b[k][2] >= b[p][2]) sh = false; if (b[k][3] <= b[p][3]) sl = false; }
    if (sh) hi.push(b[p][2]); if (sl) lo.push(b[p][3]);
  }
  if (hi.length < 2 || lo.length < 2) return 0;
  const hh = hi.at(-1) > hi.at(-2), hl = lo.at(-1) > lo.at(-2), lh = hi.at(-1) < hi.at(-2), ll = lo.at(-1) < lo.at(-2);
  return hh && hl ? 1 : lh && ll ? -1 : 0;
}

// all four timeframes, with the indicator's overlap rule (higher timeframe kept, tagged "also 4H")
const TFS = [['W', { ext: true }], ['D', {}], ['4H', { flips: true }], ['1H', { flips: true }]];
function allZones(bars) {        // bars = { W:[], D:[], '4H':[], '1H':[] }
  const zs = [];
  for (const [tf, o] of TFS) for (const z of structureZones(bars[tf] || [], o)) zs.push({ ...z, tf, also: [] });
  const rank = { W: 3, D: 2, '4H': 1, '1H': 0 };
  for (const z of zs) {
    const hi = zs.filter(y => rank[y.tf] > rank[z.tf] && y.kind === z.kind && z.top >= y.bot && z.bot <= y.top);
    if (hi.length) { z.hidden = true; for (const y of hi) if (!y.also.includes(z.tf)) y.also.push(z.tf); }
  }
  return zs.filter(z => !z.hidden);
}

if (typeof module !== 'undefined') module.exports = { atr, structureZones, trend, allZones };
