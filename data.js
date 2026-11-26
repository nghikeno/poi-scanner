// Candles from Deriv's public data feed (no login), built into TradingView-style 4H / Daily / Weekly candles.
'use strict';
const WS_URL = 'wss://api.derivws.com/trading/v1/options/ws/public';

// TradingView's Deriv session: a day starts at 17:00 New York time
function nyParts(t) {
  const f = new Intl.DateTimeFormat('en-US', { timeZone: 'America/New_York', hourCycle: 'h23',
    year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', weekday: 'short' });
  const p = Object.fromEntries(f.formatToParts(new Date(t * 1000)).map(x => [x.type, x.value]));
  return p;
}
function nyOffset(t) {                         // seconds to add to UTC to get New York local time
  const p = nyParts(t);
  const local = Date.UTC(+p.year, +p.month - 1, +p.day, +p.hour, +p.minute) / 1000;
  return local - Math.floor(t / 60) * 60;
}
function dayStart(t) {                         // start (UTC seconds) of the trading day that contains t
  const off = nyOffset(t);
  const loc = t + off;                         // NY local seconds
  let s = Math.floor(loc / 86400) * 86400 + 17 * 3600;
  if (loc < s) s -= 86400;
  return s - nyOffset(s - off);                // back to UTC (offset at the session start)
}
function key(t, tf) {
  const s = dayStart(t);
  if (tf === '1D') return s;
  if (tf === '1W') {                           // week starts Sunday 17:00 New York
    const wd = new Date((s + nyOffset(s)) * 1000).getUTCDay();   // weekday of the session start (NY)
    const back = wd;                            // Sunday = 0
    return dayStart(s - back * 86400 + 3600);
  }
  if (tf === '240') return s + Math.floor((t - s) / 14400) * 14400;
}
function aggregate(h1, tf) {
  const out = [];
  for (const b of h1) {
    const k = key(b[0], tf); const o = out[out.length - 1];
    if (o && o[0] === k) { o[2] = Math.max(o[2], b[2]); o[3] = Math.min(o[3], b[3]); o[4] = b[4]; }
    else out.push([k, b[1], b[2], b[3], b[4]]);
  }
  return out;
}

function connect() {
  return new Promise((res, rej) => {
    const ws = new WebSocket(WS_URL); const waiting = new Map(); let id = 0;
    ws.onopen = () => res({
      call(req) {
        return new Promise((ok, bad) => {
          const rid = ++id; const tm = setTimeout(() => { waiting.delete(rid); bad(new Error('timeout')); }, 60000);
          waiting.set(rid, d => { clearTimeout(tm); d.error ? bad(new Error(d.error.message || JSON.stringify(d.error))) : ok(d); });
          ws.send(JSON.stringify({ ...req, req_id: rid }));
        });
      },
      close() { try { ws.close(); } catch (e) {} }
    });
    ws.onerror = e => rej(new Error('websocket error'));
    ws.onmessage = m => { const d = JSON.parse(m.data); const f = waiting.get(d.req_id); if (f) { waiting.delete(d.req_id); f(d); } };
  });
}

const sleep = ms => new Promise(r => setTimeout(r, ms));
async function candles(api, code, gran, count, end = 'latest') {
  let d;
  for (let k = 0; ; k++) {
    try { await sleep(250); d = await api.call({ ticks_history: code, style: 'candles', granularity: gran, count, end }); break; }
    catch (e) { if (k < 3 && /rate limit/i.test(e.message)) { await sleep(15000); continue; } throw e; }
  }
  return (d.candles || []).map(c => [c.epoch, +c.open, +c.high, +c.low, +c.close]);
}

// Deriv code for each TradingView symbol (found by name, so new indices work too)
const NAMES = {
  STEP_INDEX: /^Step Index( 100)?$/i, BOOM_500_INDEX: /^Boom 500 Index$/i, XAUUSD: /^(Gold\/USD|XAU\/USD)$/i,
};
function nameFor(tv) {
  if (NAMES[tv]) return NAMES[tv];
  let m = tv.match(/^VOLATILITY_(\d+)_1S_INDEX$/); if (m) return new RegExp(`^Volatility ${m[1]} \\(1s\\) Index$`, 'i');
  m = tv.match(/^VOLATILITY_(\d+)_INDEX$/); if (m) return new RegExp(`^Volatility ${m[1]} Index$`, 'i');
}
function guess(tv) {
  const fixed = { STEP_INDEX: 'stpRNG', BOOM_500_INDEX: 'BOOM500', XAUUSD: 'frxXAUUSD' };
  if (fixed[tv]) return fixed[tv];
  let m = tv.match(/^VOLATILITY_(\d+)_1S_INDEX$/); if (m) return `1HZ${m[1]}V`;
  m = tv.match(/^VOLATILITY_(\d+)_INDEX$/); if (m) return `R_${m[1]}`;
}
async function resolveCodes(api, tvList) {
  let d = {}; try { d = await api.call({ active_symbols: 'brief' }); } catch (e) { console.log('active_symbols failed', e.message); }
  const list = (d.active_symbols || []).map(s => ({ code: s.symbol || s.underlying_symbol, name: s.display_name || s.underlying_symbol_name || '' }));
  const out = {};
  const codes = new Set(list.map(s => s.code));
  for (const tv of tvList) {
    const re = nameFor(tv); const f = re && list.find(s => re.test(s.name));
    if (f) { out[tv] = f.code; continue; }
    const g = guess(tv); if (g && (codes.size === 0 || codes.has(g))) out[tv] = g;   // known codes as a fallback
  }
  return out;
}

// all candles one symbol needs. 1H history is kept in a cache (cache/<code>.json) between runs, so each run
// only asks Deriv for the newest candles; the old history is filled in one page per run (Deriv rate limits).
const fs = require('fs'), path = require('path');
const CACHE = path.join(__dirname, 'cache');
// Deriv only gives 1 year of history, so older Weekly candles come from a one-time TradingView export
const SEED = {};
try {   // format: { symbol: { t0: first week start, o: "open,high,low,close;..." } } - week times are rebuilt with key()
  const raw = JSON.parse(fs.readFileSync(path.join(__dirname, 'seed_weekly.json'), 'utf8'));
  for (const [tv, s] of Object.entries(raw)) {
    let t = s.t0;
    SEED[tv] = s.o.split(';').map((row, i) => { if (i) t = key(t + 7 * 86400 + 7200, '1W'); return [t, ...row.split(',').map(Number)]; });
  }
} catch (e) { console.log('no weekly seed', e.message); }
async function loadSymbol(api, code, now = Date.now() / 1000, tv = '') {
  if (!fs.existsSync(CACHE)) fs.mkdirSync(CACHE);
  const file = path.join(CACHE, code + '.json');
  let c = fs.existsSync(file) ? JSON.parse(fs.readFileSync(file, 'utf8')) : { h1: [], full: false };
  // Deriv returns at most 2000 candles per request and about 1 year of 1H history; pages can overlap, so
  // candles are merged by time, kept only on whole hours, and sorted.
  const merge = (...lists) => [...new Map(lists.flat().filter(b => b[0] % 3600 === 0).map(b => [b[0], b])).values()].sort((a, b) => a[0] - b[0]);
  let h1 = merge(c.h1);
  h1 = merge(h1, await candles(api, code, 3600, h1.length ? 200 : 2000));
  if (!c.full && h1.length) {                       // one older page per run until Deriv has nothing older
    const first = h1[0][0];
    h1 = merge(await candles(api, code, 3600, 2000, first - 1), h1);
    if (h1[0][0] >= first) c.full = true;
  }
  fs.writeFileSync(file, JSON.stringify({ h1, full: c.full }));
  const m15 = await candles(api, code, 900, 400);
  const m5 = await candles(api, code, 300, 300);
  const closed = (b, s) => b.filter(x => x[0] + s <= now).sort((a, b) => a[0] - b[0]);
  const h1c = closed(h1, 3600);
  const bars = {
    W: aggregate(h1c, '1W'), D: aggregate(h1c, '1D'), '4H': aggregate(h1c, '240'), '1H': h1c,
    '15m': closed(m15, 900), '5m': closed(m5, 300),
  };
  // the Weekly / Daily / 4H candle that is still forming must not count
  bars.W = bars.W.slice(1); bars.D = bars.D.slice(1);   // the first week / day of the history is only partly there
  if (SEED[tv] && bars.W.length) bars.W = SEED[tv].filter(w => w[0] < bars.W[0][0]).concat(bars.W);
  bars.W = bars.W.filter(b => key(now, '1W') !== b[0]);
  bars.D = bars.D.filter(b => key(now, '1D') !== b[0]);
  bars['4H'] = bars['4H'].filter(b => key(now, '240') !== b[0]);
  bars['4H'] = bars['4H'].slice(-3800); bars['1H'] = bars['1H'].slice(-6300);   // same history length as TradingView
  bars.live = m5;                                   // includes the forming 5m candle (live price)
  bars.full = c.full;
  return bars;
}

module.exports = { connect, candles, resolveCodes, loadSymbol, aggregate, key };
