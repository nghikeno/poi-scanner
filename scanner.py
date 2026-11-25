"""POI zone scanner for Deriv volatility indices.

Every run (GitHub Actions, every 15 minutes):
  1. downloads 15m and 1H candles from Deriv's public data feed (no login needed),
  2. builds 4H, Daily and Weekly candles the same way TradingView does,
  3. runs the POI zone rules for the 4H setup (4H zones -> 15m) and the Daily setup (Daily zones -> 1H),
  4. sends a Telegram message for every new WATCH (price reached a valid zone) and
     SETUP (W / M / break of structure confirmed) with a checklist of the soft rules.

Hard rules (always applied): zones only from swings that broke structure with a close, trade with the
trend only, no ranges, the pattern must form at the zone, target at least 1R.
Soft rules (shown as a checklist, never block an alert): EMAs lined up (4H setup), target within 4R,
first visit to the zone (Daily setup), strength of the index in the backtest.
"""
import asyncio, json, os, sys, time, urllib.parse, urllib.request
from datetime import datetime, timezone, timedelta
import websockets
import agg, engine

WS_URL = 'wss://api.derivws.com/trading/v1/options/ws/public'
# Deriv code -> (short name, TradingView symbol, backtest note)
SYMBOLS = {
    '1HZ75V':  ('V75(1s)',  'VOLATILITY_75_1S_INDEX',  'best in backtest'),
    '1HZ100V': ('V100(1s)', 'VOLATILITY_100_1S_INDEX', 'best in backtest'),
    '1HZ90V':  ('V90(1s)',  'VOLATILITY_90_1S_INDEX',  'good in backtest'),
    'R_75':    ('V75',      'VOLATILITY_75_INDEX',     'good in backtest'),
    '1HZ10V':  ('V10(1s)',  'VOLATILITY_10_1S_INDEX',  'good in backtest'),
    'R_50':    ('V50',      'VOLATILITY_50_INDEX',     'good in backtest'),
    'R_25':    ('V25',      'VOLATILITY_25_INDEX',     'average in backtest'),
    '1HZ25V':  ('V25(1s)',  'VOLATILITY_25_1S_INDEX',  'average in backtest'),
    'R_100':   ('V100',     'VOLATILITY_100_INDEX',    'average in backtest'),
    'R_10':    ('V10',      'VOLATILITY_10_INDEX',     'average in backtest'),
    '1HZ15V':  ('V15(1s)',  'VOLATILITY_15_1S_INDEX',  'average in backtest'),
    '1HZ50V':  ('V50(1s)',  'VOLATILITY_50_1S_INDEX',  'weak in backtest'),
    '1HZ150V': ('V150(1s)', 'VOLATILITY_150_1S_INDEX', 'weak in backtest'),
    '1HZ30V':  ('V30(1s)',  'VOLATILITY_30_1S_INDEX',  'WEAK in backtest (lost every trade)'),
}
WINDOW = int(os.environ.get('WINDOW_MIN', '45')) * 60   # alert on events whose candle closed in the last 45 min
STATE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'sent.json')
LOCAL = timedelta(hours=2)   # Windhoek time (UTC+2)

SETUPS = {
    '4H': dict(entry='15', poi='240', label='4H setup (4H zone -> 15m entry)', patt='15m',
               kw=dict(ent='15', tA='240', tB='1D', tW='1W', sigMode=1, useLines=False, bosZone=True,
                       use2=True, wBlock=True, maFilter=None, maxRR=0, alertMode=True)),
    'D':  dict(entry='60', poi='1D', label='Daily setup (Daily zone -> 1H entry)', patt='1H',
               kw=dict(ent='60', tA='1D', tB='1W', tW='1W', sigMode=0, bosZone=True, use2=False,
                       wBlock=False, maFilter=None, maxRR=0, maxTouch=0, alertMode=True)),
}
TFSEC = {'15': 900, '60': 3600}

async def fetch(ws, code, gran, count, end='latest'):
    req = dict(ticks_history=code, style='candles', granularity=gran, count=count, end=end)
    await ws.send(json.dumps(req))
    d = json.loads(await asyncio.wait_for(ws.recv(), 60))
    if d.get('error'): raise RuntimeError(f"{code} {gran}: {d['error']}")
    return [[c['epoch'], float(c['open']), float(c['high']), float(c['low']), float(c['close'])] for c in d['candles']]

async def get_data(code):
    async with websockets.connect(WS_URL, max_size=2**25) as ws:
        m15 = await fetch(ws, code, 900, 5000)
        h1b = await fetch(ws, code, 3600, 5000)
        h1a = await fetch(ws, code, 3600, 5000, end=h1b[0][0] - 1)
    now = time.time()
    m15 = [b for b in m15 if b[0] + 900 <= now]          # closed candles only
    h1 = [b for b in h1a + h1b if b[0] + 3600 <= now]
    seen = set(); h1 = [b for b in h1 if not (b[0] in seen or seen.add(b[0]))]
    return {'15': m15, '60': h1, '240': agg.aggregate(h1, '240'), '1D': agg.aggregate(h1, '1D'), '1W': agg.aggregate(h1, '1W')}

def ema(vals, n):
    out, a, e = [], 2 / (n + 1), None
    for v in vals:
        e = v if e is None else a * v + (1 - a) * e
        out.append(e)
    return out

def ema_ok(D, tf, t, d):
    b = [x for x in D[tf] if x[0] + int(tf) * 60 <= t]
    if len(b) < 210: return None
    c = [x[4] for x in b]; e50, e100, e200 = ema(c, 50)[-1], ema(c, 100)[-1], ema(c, 200)[-1]
    return (e50 > e100 > e200) if d == 1 else (e50 < e100 < e200)

def fmt(t): return (datetime.fromtimestamp(t, timezone.utc) + LOCAL).strftime('%d %b %H:%M')
def px(v): return f'{v:,.2f}'

def message(code, sk, ev, D):
    name, tv, note = SYMBOLS[code]; st = SETUPS[sk]; a = ev['arm']; d = ev['dir']
    side = 'BUY' if d == 1 else 'SELL'
    zone_kind = ('demand' if d == 1 else 'supply')
    ztf = {'zone': ('4H' if sk == '4H' else 'Daily'), 'big zone': 'Daily', 'line': ('4H' if sk == '4H' else 'Daily')}[a.get('src', 'zone')]
    zone = f"{ztf} trendline (3rd touch)" if a.get('src') == 'line' else f"{ztf} {zone_kind} zone {px(a['zb'])} - {px(a['zt'])}"
    link = f"https://www.tradingview.com/chart/?symbol=DERIV%3A{tv}"
    closed = ev['t'] + TFSEC[st['entry']]
    if ev['kind'] == 'watch':
        return (f"🟡 <b>WATCH {name} - {side}</b>\n{st['label']}\n"
                f"Price reached the {zone} at {fmt(closed)}.\nTrend on the {('4H' if sk == '4H' else 'Daily')}: {'up' if d == 1 else 'down'}.\n"
                f"Wait for a {'W' if d == 1 else 'M'}{'' if sk == '4H' else ' or break of structure'} on the {st['patt']} chart at the zone.\n"
                f"Index: {note}\n{link}")
    rr = abs(ev['tp'] - ev['entry']) / ev['risk'] if ev['risk'] else 0
    chk = []
    chk.append(('✅' if rr <= 4 else '❌') + f" target within 4R (this one {rr:.1f}R)")
    if sk == '4H':
        e4, e1 = ema_ok(D, '240', closed, d), ema_ok(D, '60', closed, d)
        chk.append(('✅' if e4 else '❌') + ' 4H EMAs 50/100/200 lined up')
        chk.append(('✅' if e1 else '❌') + ' 1H EMAs 50/100/200 lined up')
    else:
        fresh = a.get('ztouch', 1) == 1 if a.get('src') != 'line' else None
        if fresh is not None: chk.append(('✅' if fresh else '❌') + ' first visit to this zone')
        chk.append(('✅' if a.get('src') != 'line' else 'ℹ️') + (' zone entry' if a.get('src') != 'line' else ' trendline entry (weaker in backtest)'))
    chk.append(('✅' if 'best' in note or 'good' in note else ('⚠️' if 'WEAK' in note or 'weak' in note else '➖')) + f" index: {note}")
    allok = all(c.startswith('✅') for c in chk)
    return (f"🟢 <b>SETUP {name} - {side} ({ev['why']})</b>\n{st['label']}\n"
            f"{ev['why'].split(' ')[0]} confirmed on the {st['patt']} candle that closed at {fmt(closed)}.\n"
            f"Zone: {zone}\n"
            f"Entry ≈ {px(ev['entry'])}\nStop {px(ev['stop'])}\nTarget {px(ev['tp'])} (latest {'4H' if sk == '4H' else 'Daily'} swing)\n"
            f"Reward:risk {rr:.2f}\n\n" + '\n'.join(chk) +
            ("\n\n⭐ Meets every backtested rule." if allok else "\n\nSome soft rules not met - your call.") +
            f"\nCheck the chart before trading:\n{link}")

def send(text):
    if os.environ.get('DRY_RUN'):
        print('---- MESSAGE ----\n' + text); return
    tok, chat = os.environ['TELEGRAM_TOKEN'], os.environ['TELEGRAM_CHAT_ID']
    data = urllib.parse.urlencode(dict(chat_id=chat, text=text, parse_mode='HTML', disable_web_page_preview='true')).encode()
    urllib.request.urlopen(f'https://api.telegram.org/bot{tok}/sendMessage', data, timeout=30).read()

def scan(code, D, now, sent):
    new = []
    for sk, st in SETUPS.items():
        try:
            events = engine.run(code, data=D, **st['kw'])
        except Exception as e:
            print('engine error', code, sk, e); continue
        for ev in events:
            closed = ev['t'] + TFSEC[st['entry']]
            if not (now - WINDOW <= closed <= now): continue
            k = f"{code}|{sk}|{ev['kind']}|{ev['dir']}|{ev['t']}"
            if k in sent: continue
            new.append((k, message(code, sk, ev, D)))
    return new

def main():
    now = time.time()
    if os.environ.get('SEND_TEST') == 'true':
        send('✅ Test message from your POI zone scanner. Telegram is set up correctly.')
    sent = json.load(open(STATE)) if os.path.exists(STATE) else []
    total = 0; errors = []
    for code in SYMBOLS:
        try:
            D = asyncio.run(get_data(code))
        except Exception as e:
            errors.append(f'{code}: {e}'); continue
        for k, text in scan(code, D, now, set(sent)):
            send(text); sent.append(k); total += 1
    utc = datetime.now(timezone.utc)
    if utc.hour == 4 and utc.minute < 15 and not os.environ.get('NO_HEARTBEAT'):   # 06:00-06:15 Windhoek time
        send(f"✅ Scanner is running. Watching {len(SYMBOLS) - len(errors)} indices." + (f"\nProblems: {errors}" if errors else ''))
    json.dump(sent[-1000:], open(STATE, 'w'))
    print(f'done: {total} alerts, errors: {errors}')
    if errors and len(errors) == len(SYMBOLS): sys.exit(1)

if __name__ == '__main__':
    main()
