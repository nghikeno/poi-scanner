"""Build 4H, Daily and Weekly candles from 1H candles using TradingView's Deriv session:
days start at 17:00 New York time (21:00 UTC in summer, 22:00 UTC in winter)."""
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
NY = ZoneInfo('America/New_York')
def _day_start(t):
    d = datetime.fromtimestamp(t, timezone.utc).astimezone(NY)
    s = d.replace(hour=17, minute=0, second=0, microsecond=0)
    if d < s: s -= timedelta(days=1)
    return s
def key(t, tf):
    s = _day_start(t)
    if tf == '1D': return int(s.timestamp())
    if tf == '1W':
        # week starts Sunday 17:00 NY
        back = (s.weekday() + 1) % 7   # Monday=0 -> 1 day back to Sunday
        return int((s - timedelta(days=back)).timestamp())
    if tf == '240':
        h = int((t - s.timestamp()) // 14400)
        return int(s.timestamp()) + h * 14400
def aggregate(h1, tf):
    out = []
    for b in h1:
        k = key(b[0], tf)
        if out and out[-1][0] == k:
            o = out[-1]; o[2] = max(o[2], b[2]); o[3] = min(o[3], b[3]); o[4] = b[4]
        else:
            out.append([k, b[1], b[2], b[3], b[4]])
    return out
