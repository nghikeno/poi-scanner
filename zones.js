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
// FLIPPED zones (every timeframe): a swing broken by a candle CLOSE flips (old high -> demand, old low -> supply).
// Swings broken by the same candle and within 1 ATR of the newest one form one zone: furthest wick to the body edge
// of the newest swing. Shown only if never closed back through (0.25 ATR), inside the current range (between the
// fresh supply and fresh demand; no limit on a side without one), not on the fresh zone, swing within the last 100
// candles, and per side only the one nearest to price.
function structureZones(b, opt) {
  const ext = !!(opt && opt.ext), flips = !(opt && opt.flips === false), n = 2, minBars = 52, lookN = (opt && opt.lookN) || 100;
  const NN = b.length, out = [];
  if (NN < minBars || NN <= 4 * n) return out;
  // ATR (RMA 14) of closed candles
  let a1 = null, sum = 0;
  for (let i = 0; i < NN; i++) {
    const t = i === 0 ? b[i][2] - b[i][3] : Math.max(b[i][2] - b[i][3], Math.abs(b[i][2] - b[i - 1][4]), Math.abs(b[i][3] - b[i - 1][4]));
    if (i < 14) { sum += t; if (i === 13) a1 = sum / 14; } else a1 = (a1 * 13 + t) / 14;
  }
  if (!(a1 > 0)) return out;
  const H = i => b[i][2], L = i => b[i][3], C = i => b[i][4], O = i => b[i][1], T = i => b[i][0];
  const uh = [], ul = [], gH = [], gL = [];   // gH/gL: breaks = { i: break candle, p: [broken swings, newest first] }
  let minH = null, maxL = null, iU = -1, iD = -1;
  for (let i = 2 * n; i < NN; i++) {
    const c = C(i);
    if (minH !== null && c > minH) {
      iU = i; minH = null; const g = [];
      for (let q = uh.length - 1; q >= 0; q--) {
        const pq = uh[q];
        if (H(pq) < c) { g.push(pq); uh.splice(q, 1); }
        else if (minH === null || H(pq) < minH) minH = H(pq);
      }
      if (g.length) { gH.push({ i, p: g }); if (gH.length > 300) gH.shift(); }
    }
    if (maxL !== null && c < maxL) {
      iD = i; maxL = null; const g = [];
      for (let q = ul.length - 1; q >= 0; q--) {
        const pq = ul[q];
        if (L(pq) > c) { g.push(pq); ul.splice(q, 1); }
        else if (maxL === null || L(pq) > maxL) maxL = L(pq);
      }
      if (g.length) { gL.push({ i, p: g }); if (gL.length > 300) gL.shift(); }
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
  const bt3 = k => Math.max(bodyTop(Math.max(k - 1, 0)), bodyTop(k), bodyTop(Math.min(k + 1, NN - 1)));
  const bb3 = k => Math.min(bodyBot(Math.max(k - 1, 0)), bodyBot(k), bodyBot(Math.min(k + 1, NN - 1)));
  let fsup = null, fdem = null;
  if (sI >= 0) {
    const zt = H(sI), zb = Math.min(bt3(sI), zt - 0.05 * a1);
    let ok = true; for (let k = sI + 1; k < NN; k++) if (C(k) > zt + 0.25 * a1) { ok = false; break; }
    if (ok) { fsup = { top: zt, bot: zb, kind: -1, t: T(sI), fl: false }; out.push(fsup); }
  }
  if (dI >= 0) {
    const zb = L(dI), zt = Math.max(bb3(dI), zb + 0.05 * a1);
    let ok = true; for (let k = dI + 1; k < NN; k++) if (C(k) < zb - 0.25 * a1) { ok = false; break; }
    if (ok) { fdem = { top: zt, bot: zb, kind: 1, t: T(dI), fl: false }; out.push(fdem); }
  }
  if (flips) {
    // current range of this timeframe: between its fresh supply and fresh demand.
    // Where a side has no fresh zone (price already broke it), the nearest flipped zone on that side is shown.
    const rHi = fsup ? fsup.top : Infinity, rLo = fdem ? fdem.bot : -Infinity;
    const cl = C(NN - 1);
    // broken swing highs -> demand; nearest one below price inside the range
    let best = null;
    for (let q = gH.length - 1; q >= 0; q--) {
      const g = gH[q], p = g.p[0];
      let zt = H(p); for (const m of g.p) if (Math.abs(H(m) - H(p)) <= a1 && H(m) > zt) zt = H(m);
      const zb = Math.min(bt3(p), zt - 0.05 * a1);
      if (p < NN - lookN || zb > cl || zb < rLo - 0.25 * a1 || zt > (fsup ? fsup.bot : Infinity)) continue;   // stays below the fresh supply
      if (best && zt <= best.top) continue;   // nearest to price
      if (fdem && fdem.top >= zb && fdem.bot <= zt) continue;
      let ok = true; for (let k = g.i; k < NN; k++) if (C(k) < zb - 0.25 * a1) { ok = false; break; }
      if (ok) best = { top: zt, bot: zb, kind: 1, t: T(p), fl: true };
    }
    if (best) out.push(best);
    // broken swing lows -> supply; nearest one above price inside the range
    best = null;
    for (let q = gL.length - 1; q >= 0; q--) {
      const g = gL[q], p = g.p[0];
      let zb = L(p); for (const m of g.p) if (Math.abs(L(m) - L(p)) <= a1 && L(m) < zb) zb = L(m);
      const zt = Math.max(bb3(p), zb + 0.05 * a1);
      if (p < NN - lookN || zt < cl || zt > rHi + 0.25 * a1 || zb < (fdem ? fdem.top : -Infinity)) continue;   // stays above the fresh demand
      if (best && zb >= best.bot) continue;   // nearest to price
      if (fsup && fsup.top >= zb && fsup.bot <= zt) continue;
      let ok = true; for (let k = g.i; k < NN; k++) if (C(k) > zt + 0.25 * a1) { ok = false; break; }
      if (ok) best = { top: zt, bot: zb, kind: -1, t: T(p), fl: true };
    }
    if (best) out.push(best);
  }
  return out;
}


// direction of the latest structure break: +1 = the last break was a close above a swing high, -1 = below a swing low
function lastBreak(b, n = 2) {
  let uh = [], ul = [], iU = -1, iD = -1;
  for (let i = 2 * n; i < b.length; i++) {
    const c = b[i][4];
    if (uh.some(p => b[p][2] < c)) { iU = i; uh = uh.filter(p => b[p][2] >= c); }
    if (ul.some(p => b[p][3] > c)) { iD = i; ul = ul.filter(p => b[p][3] <= c); }
    const p = i - n; let sh = true, sl = true;
    for (let k = p - n; k <= p + n; k++) { if (k === p) continue; if (b[k][2] >= b[p][2]) sh = false; if (b[k][3] <= b[p][3]) sl = false; }
    if (sh) uh.push(p); if (sl) ul.push(p);
  }
  return iU > iD ? 1 : iD > iU ? -1 : 0;
}

// trend of a timeframe: last two swing highs and lows (2 candles each side) AND the latest structure break must agree
function trend(b, n = 2) {
  const hi = [], lo = [];
  for (let p = n; p < b.length - n; p++) {
    let sh = true, sl = true;
    for (let k = p - n; k <= p + n; k++) { if (k === p) continue; if (b[k][2] >= b[p][2]) sh = false; if (b[k][3] <= b[p][3]) sl = false; }
    if (sh) hi.push(b[p][2]); if (sl) lo.push(b[p][3]);
  }
  if (hi.length < 2 || lo.length < 2) return 0;
  const hh = hi.at(-1) > hi.at(-2), hl = lo.at(-1) > lo.at(-2), lh = hi.at(-1) < hi.at(-2), ll = lo.at(-1) < lo.at(-2);
  const br = lastBreak(b, n);
  return hh && hl && br === 1 ? 1 : lh && ll && br === -1 ? -1 : 0;
}

// all four timeframes, with the indicator's overlap rule (higher timeframe kept, tagged "also 4H")
const TFS = [['W', { ext: true }], ['D', {}], ['4H', {}], ['1H', {}]];
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

if (typeof module !== 'undefined') module.exports = { atr, structureZones, trend, lastBreak, allZones };
