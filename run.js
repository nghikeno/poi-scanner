// POI zone alerts for the whole watchlist -> Telegram.
// Runs every 5 minutes (GitHub Actions, started by cron-job.org). Needs TELEGRAM_TOKEN and TELEGRAM_CHAT_ID.
'use strict';
const fs = require('fs'), path = require('path');
const { connect, resolveCodes, loadSymbol } = require('./data.js');
const { allZones } = require('./zones.js');
const { check, ENTRY_TF } = require('./alerts.js');

const WATCHLIST = [
  'VOLATILITY_75_INDEX', 'VOLATILITY_75_1S_INDEX', 'VOLATILITY_25_INDEX', 'VOLATILITY_10_INDEX', 'VOLATILITY_25_1S_INDEX',
  'VOLATILITY_100_INDEX', 'VOLATILITY_50_1S_INDEX', 'VOLATILITY_10_1S_INDEX', 'VOLATILITY_15_INDEX', 'VOLATILITY_100_1S_INDEX',
  'VOLATILITY_30_1S_INDEX', 'VOLATILITY_15_1S_INDEX', 'VOLATILITY_90_1S_INDEX', 'VOLATILITY_50_INDEX', 'VOLATILITY_150_1S_INDEX',
  'VOLATILITY_30_INDEX', 'VOLATILITY_5_INDEX', 'VOLATILITY_5_1S_INDEX', 'VOLATILITY_90_INDEX', 'STEP_INDEX', 'BOOM_500_INDEX', 'XAUUSD',
];
const STATE = path.join(__dirname, 'state.json');
const LOCAL = 2 * 3600;                                    // Windhoek time (UTC+2)
// which zones give APPROACHING / TOUCH / W-M / BROKEN alerts (1H zones still show as "also 1H" on bigger zones)
const ALERT_TFS = (process.env.ALERT_TFS || 'W,D,4H').split(',');
const ALERT_FLIPPED = process.env.ALERT_FLIPPED === 'true';

const short = tv => tv.replace(/^VOLATILITY_(\d+)_1S_INDEX$/, 'V$1(1s)').replace(/^VOLATILITY_(\d+)_INDEX$/, 'V$1')
  .replace('STEP_INDEX', 'Step Index').replace('BOOM_500_INDEX', 'Boom 500').replace('XAUUSD', 'Gold');
const tm = t => new Date((t + LOCAL) * 1000).toISOString().slice(5, 16).replace('T', ' ').replace(/^(\d\d)-(\d\d)/, '$2/$1');
const dec = v => Math.abs(v) >= 1000 ? 2 : Math.abs(v) >= 10 ? 3 : 4;
const px = v => v == null ? '-' : v.toLocaleString('en-US', { minimumFractionDigits: dec(v), maximumFractionDigits: dec(v) });
const tfName = { W: 'Weekly', D: 'Daily', '4H': '4H', '1H': '1H' };
function zoneTxt(z) {
  return `${tfName[z.tf]} ${z.kind === 1 ? 'demand' : 'supply'}${z.fl ? ' (flipped)' : ''} ${px(z.bot)} - ${px(z.top)}` +
    (z.also && z.also.length ? ` (also ${z.also.join(', ')})` : '');
}
const link = tv => `https://www.tradingview.com/chart/?symbol=DERIV%3A${tv}`;

function message(tv, e) {
  const n = short(tv), z = e.z, side = z.kind === 1 ? 'BUY' : 'SELL';
  if (e.type === 'near') return `🟡 <b>${n} approaching zone</b>\n${zoneTxt(z)}\nPrice ${px(e.price)} is ${px(e.d)} away.\n${link(tv)}`;
  if (e.type === 'touch') return `🟠 <b>${n} touched zone</b>\n${zoneTxt(z)}\nPrice ${px(e.price)}. Watch the ${ENTRY_TF[z.tf]} chart for ${z.kind === 1 ? 'a W' : 'an M'}.\n${link(tv)}`;
  if (e.type === 'broken') return `⚫ <b>${n} zone broken</b>\n${zoneTxt(z)}\nA ${tfName[z.tf]} candle closed through it (close ${px(e.price)}). Setup cancelled.\n${link(tv)}`;
  const chk = [];
  chk.push((e.rr != null && e.rr >= 1 ? '✅' : '❌') + ` reward:risk ${e.rr == null ? 'unknown' : e.rr.toFixed(2)} (minimum 1)`);
  if (z.tf === '4H') chk.push((e.rr != null && e.rr <= 4 ? '✅' : '❌') + ' target within 4R');
  chk.push((e.trend === z.kind ? '✅ with' : e.trend === 0 ? '❌ range on' : '❌ against') + ` the ${tfName[z.tf]} trend`);
  return `🟢 <b>${n} ${side} - ${z.kind === 1 ? 'W' : 'M'} complete</b>\n${zoneTxt(z)}\n` +
    `${ENTRY_TF[z.tf]} candle closed beyond the neckline ${px(e.neck)} at ${tm(e.at + ({ '4H': 14400, '1H': 3600, '15m': 900, '5m': 300 })[ENTRY_TF[z.tf]])}.\n` +
    `Entry ≈ ${px(e.entry)}\nStop ${px(e.stop)}\nTarget ${px(e.tp)}\n` + chk.join('\n') + `\nCheck the chart first:\n${link(tv)}`;
}

async function send(text) {
  if (process.env.DRY_RUN) { console.log('---- MESSAGE ----\n' + text); return; }
  const r = await fetch(`https://api.telegram.org/bot${process.env.TELEGRAM_TOKEN}/sendMessage`, {
    method: 'POST', headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ chat_id: process.env.TELEGRAM_CHAT_ID, text, parse_mode: 'HTML', disable_web_page_preview: true }),
  });
  if (!r.ok) console.log('telegram error', r.status, await r.text());
}

async function main() {
  const now = Math.floor(Date.now() / 1000);
  const state = fs.existsSync(STATE) ? JSON.parse(fs.readFileSync(STATE, 'utf8')) : {};
  state.sym = state.sym || {};
  if (process.env.SEND_TEST === 'true') await send('✅ Test message from your POI zone alerts. Telegram is set up correctly.');
  const api = await connect();
  const codes = await resolveCodes(api, WATCHLIST); api.close();
  const errors = [], msgs = [], missing = [], loading = []; let ok = 0;
  const queue = WATCHLIST.slice();
  async function worker() {
    const a = await connect();
    try {
      while (queue.length) {
        const tv = queue.shift();
        if (!codes[tv]) { missing.push(short(tv)); continue; }
        try {
          const bars = await loadSymbol(a, codes[tv], now, tv);
          const zones = allZones(bars).filter(z => ALERT_TFS.includes(z.tf) && (ALERT_FLIPPED || !z.fl));
          const st = state.sym[tv] || (state.sym[tv] = {});
          if (bars.full) for (const e of check(bars, zones, st, now)) msgs.push(message(tv, e));   // only once the history is complete
          else loading.push(short(tv));
          ok++;
        } catch (e) { errors.push(`${short(tv)}: ${e.message}`); }
      }
    } finally { a.close(); }
  }
  await Promise.all([worker(), worker()]);
  for (const m of msgs) await send(m);
  // daily "still running" message: the first run after 06:00 Windhoek time
  const day = new Date((now + LOCAL) * 1000).toISOString().slice(0, 10), hour = new Date((now + LOCAL) * 1000).getUTCHours();
  if (hour >= 6 && state.heartbeat !== day) {
    await send(`✅ POI alerts running. Watching ${ok} of ${WATCHLIST.length} instruments.` + (missing.length ? `\nNot on Deriv's public data feed: ${missing.join(', ')}` : '') + (errors.length ? `\nProblems: ${errors.join('; ')}` : ''));
    state.heartbeat = day;
  }
  if (ok === 0 && (!state.lastError || now - state.lastError > 7200)) {
    await send(`❌ POI alerts could not read any data: ${errors.slice(0, 3).join('; ')}`); state.lastError = now;
  }
  fs.writeFileSync(STATE, JSON.stringify(state));
  console.log(`done: ${ok} ok, still loading history: ${loading.join(', ')}, ${msgs.length} alerts, missing: ${missing.join(', ')}, errors: ${errors.join('; ')}`);
}
main().catch(e => { console.error(e); process.exit(1); });
