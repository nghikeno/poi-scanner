"""Python copy of the POI v2 Pine strategy, run on the saved candle data.
Bars: [time, open, high, low, close]. Chart (entry) TF = 15m."""
import json, bisect, math

DATA = '/home/claude/data/deriv_candles_2026-11-25.json'
SPREAD = {'VOLATILITY_75_INDEX': 15.78, 'VOLATILITY_75_1S_INDEX': 1.22, 'VOLATILITY_25_INDEX': 0.331,
          'VOLATILITY_50_INDEX': 0.0130, 'VOLATILITY_10_INDEX': 0.188, 'VOLATILITY_10_1S_INDEX': 0.38,
          'VOLATILITY_30_1S_INDEX': 0.786}
_cache = None
def load():
    global _cache
    if _cache is None:
        _cache = json.load(open(DATA))['data']
    return _cache

def atr_rma(bars, n=14):
    out = [math.nan] * len(bars); tr = []
    prev = None
    for i, b in enumerate(bars):
        h, l, c = b[2], b[3], b[4]
        t = h - l if prev is None else max(h - l, abs(h - prev), abs(l - prev))
        prev = c
        tr.append(t)
        if i == n - 1:
            out[i] = sum(tr[:n]) / n
        elif i >= n:
            out[i] = (out[i - 1] * (n - 1) + t) / n
    return out

def ema(vals, n):
    out = []; a = 2 / (n + 1); e = None
    for v in vals:
        e = v if e is None else a * v + (1 - a) * e
        out.append(e)
    return out

def pivots(bars, left, right):
    """returns dict confirm_index -> (pivot_index) for highs and lows (strict)"""
    ph, pl = {}, {}
    for i in range(left + right, len(bars)):
        p = i - right
        hp, lp = bars[p][2], bars[p][3]
        if all(hp > bars[j][2] for j in range(p - left, p)) and all(hp > bars[j][2] for j in range(p + 1, i + 1)):
            ph[i] = p
        if all(lp < bars[j][3] for j in range(p - left, p)) and all(lp < bars[j][3] for j in range(p + 1, i + 1)):
            pl[i] = p
    return ph, pl

def htf_pack(bars, hPiv):
    """values available when HTF bar k is the *current* bar (i.e. computed on bar k-1)."""
    ph, pl = pivots(bars, hPiv, hPiv)
    at = atr_rma(bars)
    n = len(bars); pack = [None] * n
    for k in range(1, n):
        j = k - 1
        def bt(o):
            return max(bars[o][1], bars[o][4])
        def bb(o):
            return min(bars[o][1], bars[o][4])
        vPH = bars[ph[j]][2] if j in ph else None
        vPL = bars[pl[j]][3] if j in pl else None
        p = j - hPiv
        if p - 1 >= 0 and p + 1 < n:
            vBT = max(bt(p), bt(p + 1), bt(p - 1)); vBB = min(bb(p), bb(p + 1), bb(p - 1))
        else:
            vBT = vBB = None
        aPT = bars[k - hPiv - 1][0] if k - hPiv - 1 >= 0 else None
        pack[k] = dict(PH=vPH, PL=vPL, BT=vBT, BB=vBB, PT=aPT, C=bars[j][4], H=bars[j][2], L=bars[j][3],
                       ATR=at[j], T=bars[j][0])
    return pack

def map_htf(ltf, htf):
    times = [b[0] for b in htf]
    idx = []
    for b in ltf:
        k = bisect.bisect_right(times, b[0]) - 1
        idx.append(k)
    return idx

P = dict(hPiv=3, maxZ=3, useZones=True, useLines=True, use2=True, lPivL=1, lPiv=2, maxWait=48, farR=0.5, minRR=1.0,
         invK=0.25, wTolK=0.3, rngK=0.5, strict=True, wBlock=True, oneUse=False, sigMode=0, partMode=0,
         maFilter=None, alertMode=False, reclaim=False, maxTouch=0, maxAgeD=0, minZW=0, nearAlways=False, ltfInv=False, ltfK=0.0, ltfN=1, ltfAny=False, bosZone=False, tpCap=None, maxRR=None, beR=None, maxRet=None, ent='15', tA='240', tB='1D', tW='1W', warm=False)

def run(sym, data=None, **over):
    p = dict(P); p.update(over)
    D = data if data is not None else load()[sym]; sp = SPREAD.get(sym, 0.0)
    events = []
    b15 = D[p['ent']]; b4 = D[p['tA']]; bD = D[p['tB']]; bW = D[p['tW']]; b1 = D.get('60')
    if p['warm']:
        pre = [b for b in D[p['warm']] if b[0] < b15[0][0]]
        b15 = pre + b15
    tfsec = {'15':900,'60':3600,'240':14400}[p['ent']]
    pA = htf_pack(b4, p['hPiv']); pB = htf_pack(bD, p['hPiv']); pW = htf_pack(bW, p['hPiv'])
    iA = map_htf(b15, b4); iB = map_htf(b15, bD); iW = map_htf(b15, bW)
    at15 = atr_rma(b15)
    hPiv = p['hPiv']
    # MA helpers: value of last *closed* HTF bar
    maf = p['maFilter']
    ma = {}
    if maf:
        for tfk, bars in (('1d', D['1D']), ('4h', D['240']), ('1h', b1)):
            closes = [b[4] for b in bars]
            ma[tfk] = dict(bars=bars, idx=map_htf(b15, bars), close=closes,
                           e50=ema(closes, 50), e100=ema(closes, 100), e200=ema(closes, 200))
    # 15m pivots (left lPivL, right lPiv)
    ph15, pl15 = pivots(b15, p['lPivL'], p['lPiv'])

    zones = []  # dict(top,bot,kind,tf,t,fl,used,id)
    zseq = [0]
    def inZone(x):
        return any(z['bot'] <= x <= z['top'] for z in zones)
    def addZone(t, b, k, tf, tm):
        zseq[0] += 1
        zones.append(dict(top=t, bot=b, kind=k, tf=tf, t=tm, fl=False, used=False, id=zseq[0]))
        cnt = 0
        for i in range(len(zones) - 1, -1, -1):
            z = zones[i]
            if z['kind'] == k and z['tf'] == tf and not z['fl']:
                cnt += 1
                if cnt > p['maxZ']:
                    zones.pop(i)
    def updZones(tf, c, at):
        for i in range(len(zones) - 1, -1, -1):
            z = zones[i]
            if z['tf'] != tf: continue
            if z['kind'] == -1 and c > z['top'] + p['invK'] * at:
                if z['fl']: zones.pop(i)
                else: z['kind'] = 1; z['fl'] = True; z['used'] = False; z['dead'] = False; z['nb'] = 0
            elif z['kind'] == 1 and c < z['bot'] - p['invK'] * at:
                if z['fl']: zones.pop(i)
                else: z['kind'] = -1; z['fl'] = True; z['used'] = False; z['dead'] = False; z['nb'] = 0
    pendZ = []
    t4l = [x[0] for x in b4]; tDl = [x[0] for x in bD]
    def tryZone(top, bot, k, tf, tm, ref, swing):
        if not p['bosZone']:
            if not inZone(bot if k == -1 else top): addZone(top, bot, k, tf, tm)
            return
        pendZ.append(dict(top=top, bot=bot, k=k, tf=tf, tm=tm, ref=ref, sw=swing, n=0))
    def checkPend(tf, lastT):
        bars = b4 if tf == 1 else bD; tl = t4l if tf == 1 else tDl
        for q in list(pendZ):
            if q['tf'] != tf: continue
            if q['ref'] is None: pendZ.remove(q); continue
            i0 = bisect.bisect_left(tl, q['tm']); i1 = bisect.bisect_right(tl, lastT) - 1
            seg = bars[i0 + 1:i1 + 1]
            if q['k'] == -1:
                broke = any(x[4] < q['ref'] for x in seg); beaten = any(x[2] > q['sw'] for x in seg)
            else:
                broke = any(x[4] > q['ref'] for x in seg); beaten = any(x[3] < q['sw'] for x in seg)
            if beaten or len(seg) > 60: pendZ.remove(q); continue
            if broke:
                pendZ.remove(q)
                if not inZone(q['bot'] if q['k'] == -1 else q['top']): addZone(q['top'], q['bot'], q['k'], q['tf'], q['tm'])
    def lineAt(p1, t1, p2, t2, t):
        if p1 is None or t2 == t1: return None
        return p1 + (p2 - p1) * (t - t1) / (t2 - t1)

    S = dict(lastHi=None, lastLo=None, lastHiT=None, lastLoT=None, prevHi=None, prevLo=None, prevHiT=None, prevLoT=None,
             trend=0, u=None, uN=0, d=None, dN=0, dHi=None, dHi0=None, dLo=None, dLo0=None, dTrend=0,
             wHiT=None, wHiB=None, wLoT=None, wLoB=None)
    hiP, hiT, loP, loT = [], [], [], []
    arm = dict(dir=0)
    pos = None  # open position
    trades = []
    pending = None  # entry order to fill next bar
    prevA = prevB = prevW = None
    aT_prev = None

    def ctl(d, t):
        if d == 1 and len(hiP) >= 2:
            p2, t2 = hiP[-1], hiT[-1]
            for j in range(len(hiP) - 2, -1, -1):
                if hiP[j] > p2: return lineAt(hiP[j], hiT[j], p2, t2, t)
        if d == -1 and len(loP) >= 2:
            p2, t2 = loP[-1], loT[-1]
            for j in range(len(loP) - 2, -1, -1):
                if loP[j] < p2: return lineAt(loP[j], loT[j], p2, t2, t)
        return None

    def ma_ok(d, i):
        if not maf: return True
        for tfk, rule in maf.items():
            m = ma[tfk]; k = m['idx'][i] - 1   # last closed HTF bar
            if k < 200: return False
            c, e50, e100, e200 = m['close'][k], m['e50'][k], m['e100'][k], m['e200'][k]
            if rule == 'stack':
                ok = (e50 > e100 > e200) if d == 1 else (e50 < e100 < e200)
            elif rule == '200':
                ok = (c > e200) if d == 1 else (c < e200)
            elif rule == '50_200':
                ok = (e50 > e200) if d == 1 else (e50 < e200)
            elif rule == 'stack_price':
                ok = (c > e50 > e100 > e200) if d == 1 else (c < e50 < e100 < e200)
            elif rule == '50':
                ok = (c > e50) if d == 1 else (c < e50)
            else:
                ok = True
            if not ok: return False
        return True

    n = len(b15)
    for i in range(n):
        t, o, h, l, c = b15[i]
        # ---------- fill pending entry at this bar's open, then manage exits within the bar
        ka, kb, kw = iA[i], iB[i], iW[i]
        A = pA[ka] if ka >= 1 else None
        B = pB[kb] if kb >= 1 else None
        Wp = pW[kw] if kw >= 1 else None
        if pending is not None:
            d = pending['dir']
            ent = o
            pos = dict(dir=d, entry=ent, stop=pending['stop'], tp=pending['tp'], rk=pending['rk'], why=pending['why'],
                       src=pending['src'], sigT=pending['sigT'], fillT=t, half=False, curStop=pending['stop'], trail=False,
                       sigClose=pending['sigClose'], qty_open=2, pnl=0.0, extra={k:pending[k] for k in ('arm','atr4','trend','dT','lastHi','lastLo','prevHi','prevLo','w')})
            pending = None
        if pos is not None:
            # exits evaluated intrabar on this bar (path: open -> nearer extreme -> other -> close)
            d = pos['dir']
            path = [o, h, l, c] if abs(o - h) <= abs(o - l) else [o, l, h, c]
            def try_exit():
                # returns exit price or None, handles partial
                pass
            stopL = pos['curStop'] if d == 1 else pos['curStop'] - sp
            tpL = pos['tp'] if d == 1 else pos['tp'] - sp
            oneR = (pos['sigClose'] + pos['rk']) if d == 1 else (pos['sigClose'] - pos['rk'] - sp)
            done = False
            # walk the path segments
            cur = path[0]
            # gap at open
            events = []
            for seg in range(1, 4):
                a_, b_ = path[seg - 1], path[seg]
                lo_, hi_ = min(a_, b_), max(a_, b_)
                lvls = []
                if d == 1:
                    if stopL >= lo_ and stopL <= hi_: lvls.append(('stop', stopL))
                    if tpL is not None and lo_ <= tpL <= hi_: lvls.append(('tp', tpL))
                    if p['partMode'] in (1, 2) and not pos['half'] and lo_ <= oneR <= hi_: lvls.append(('half', oneR))
                else:
                    if lo_ <= stopL <= hi_: lvls.append(('stop', stopL))
                    if tpL is not None and lo_ <= tpL <= hi_: lvls.append(('tp', tpL))
                    if p['partMode'] in (1, 2) and not pos['half'] and lo_ <= oneR <= hi_: lvls.append(('half', oneR))
                # order by distance from segment start
                lvls.sort(key=lambda x: abs(x[1] - a_))
                for name, lv in lvls:
                    if seg == 1 and ((d == 1 and name == 'stop' and o <= stopL) or (d == -1 and name == 'stop' and o >= stopL)):
                        lv = o
                    if seg == 1 and name in ('tp', 'half') and ((d == 1 and o >= lv) or (d == -1 and o <= lv)):
                        lv = o
                    if name == 'half':
                        pos['pnl'] += (lv - pos['entry']) * d * 1 - sp
                        pos['qty_open'] = 1; pos['half'] = True
                        if p['partMode'] == 2:
                            pos['curStop'] = pos['entry']
                            stopL = pos['entry'] if d == 1 else pos['entry'] - sp
                        continue
                    q = pos['qty_open']
                    pos['pnl'] += ((lv - pos['entry']) * d - sp) * q
                    qtot = 2
                    r = pos['pnl'] / (qtot * pos['rk'])
                    trades.append(dict(extra=pos['extra'], fillT=pos['fillT'], sigT=pos['sigT'], dir=d, why=pos['why'], src=pos['src'], entry=pos['entry'],
                                       stop=pos['stop'], tp=pos['tp'], exitT=t, exit=lv, R=r))
                    pos = None; done = True
                    break
                if done: break
            if pos is not None and p['partMode'] >= 3:
                # trailing update at bar close (applies from next bar)
                if d == 1:
                    if not pos['trail'] and h >= pos['sigClose'] + pos['rk']: pos['trail'] = True
                else:
                    if not pos['trail'] and l <= pos['sigClose'] - pos['rk']: pos['trail'] = True
        # ---------- HTF processing (newA etc.) happens in script order: pack values first
        newA = A is not None and (prevA is None or A['T'] != prevA)
        newB = B is not None and (prevB is None or B['T'] != prevB)
        newW = Wp is not None and (prevW is None or Wp['T'] != prevW)
        if newW:
            if Wp['PH'] is not None: S['wHiT'] = Wp['PH']; S['wHiB'] = min(Wp['BT'], Wp['PH'] - 0.05 * Wp['ATR'])
            if Wp['PL'] is not None: S['wLoB'] = Wp['PL']; S['wLoT'] = max(Wp['BB'], Wp['PL'] + 0.05 * Wp['ATR'])
        inWeek = p['wBlock'] and ((S['wHiT'] is not None and S['wHiB'] <= c <= S['wHiT']) or
                                  (S['wLoT'] is not None and S['wLoB'] <= c <= S['wLoT']))
        if newA:
            if p['useZones']: updZones(1, A['C'], A['ATR'])
            if A['PH'] is not None:
                if p['useZones']:
                    tryZone(A['PH'], min(A['BT'], A['PH'] - 0.05 * A['ATR']), -1, 1, A['PT'], S['lastLo'], A['PH'])
                S['prevHi'], S['prevHiT'] = S['lastHi'], S['lastHiT']
                S['lastHi'], S['lastHiT'] = A['PH'], A['PT']
                if p['useLines'] and S['d'] is None and S['prevHi'] is not None and A['PH'] < S['prevHi']:
                    S['d'] = (S['prevHi'], S['prevHiT'], A['PH'], A['PT']); S['dN'] = 2
            if A['PL'] is not None:
                if p['useZones']:
                    tryZone(max(A['BB'], A['PL'] + 0.05 * A['ATR']), A['PL'], 1, 1, A['PT'], S['prevHi'] if A['PH'] is not None else S['lastHi'], A['PL'])
                S['prevLo'], S['prevLoT'] = S['lastLo'], S['lastLoT']
                S['lastLo'], S['lastLoT'] = A['PL'], A['PT']
                if p['useLines'] and S['u'] is None and S['prevLo'] is not None and A['PL'] > S['prevLo']:
                    S['u'] = (S['prevLo'], S['prevLoT'], A['PL'], A['PT']); S['uN'] = 2
            if p['useZones'] and p['bosZone']: checkPend(1, A['T'])
            if S['lastHi'] is not None and A['C'] > S['lastHi']: S['trend'] = 1
            if S['lastLo'] is not None and A['C'] < S['lastLo']: S['trend'] = -1
            if p['strict'] and S['trend'] == 1 and not (S['lastLo'] is not None and S['prevLo'] is not None and S['lastLo'] > S['prevLo']): S['trend'] = 0
            if p['strict'] and S['trend'] == -1 and not (S['lastHi'] is not None and S['prevHi'] is not None and S['lastHi'] < S['prevHi']): S['trend'] = 0
            tolA = 0.1 * A['ATR']
            per = (A['T'] - aT_prev) if aT_prev is not None else 0
            if S['u'] is not None:
                uv = lineAt(*S['u'], A['T'])
                if A['C'] < uv - tolA: S['u'] = None; S['uN'] = 0
                elif A['L'] <= uv + tolA and A['T'] > S['u'][3] + 2 * hPiv * per: S['uN'] += 1
            if S['d'] is not None:
                dv = lineAt(*S['d'], A['T'])
                if A['C'] > dv + tolA: S['d'] = None; S['dN'] = 0
                elif A['H'] >= dv - tolA and A['T'] > S['d'][3] + 2 * hPiv * per: S['dN'] += 1
        if newB:
            if B['PH'] is not None: S['dHi0'], S['dHi'] = S['dHi'], B['PH']
            if B['PL'] is not None: S['dLo0'], S['dLo'] = S['dLo'], B['PL']
        if newB and p['use2'] and p['useZones']:
            updZones(2, B['C'], B['ATR'])
            if B['PH'] is not None:
                tryZone(B['PH'], min(B['BT'], B['PH'] - 0.05 * B['ATR']), -1, 2, B['PT'], S['dLo0'] if B['PL'] is not None else S['dLo'], B['PH'])
            if B['PL'] is not None:
                tryZone(max(B['BB'], B['PL'] + 0.05 * B['ATR']), B['PL'], 1, 2, B['PT'], S['dHi0'] if B['PH'] is not None else S['dHi'], B['PL'])
            if p['bosZone']: checkPend(2, B['T'])
        if A is not None:
            aT_prev_new = A['T']
        # 15m pivots
        if i in ph15:
            hiP.append(b15[ph15[i]][2]); hiT.append(b15[ph15[i]][0])
            if len(hiP) > 30: hiP.pop(0); hiT.pop(0)
        if i in pl15:
            loP.append(b15[pl15[i]][3]); loT.append(b15[pl15[i]][0])
            if len(loP) > 30: loP.pop(0); loT.pop(0)
        # range
        isRange = False
        if A is not None and p['rngK'] > 0 and S['lastHi'] is not None and S['lastLo'] is not None:
            eq = ((S['prevHi'] is not None and abs(S['lastHi'] - S['prevHi']) <= p['rngK'] * A['ATR']) or
                  (S['prevLo'] is not None and abs(S['lastLo'] - S['prevLo']) <= p['rngK'] * A['ATR']))
            hiM = max(S['lastHi'], S['prevHi']) if S['prevHi'] is not None else S['lastHi']
            loM = min(S['lastLo'], S['prevLo']) if S['prevLo'] is not None else S['lastLo']
            isRange = eq and A['C'] <= hiM and A['C'] >= loM
        flat = pos is None and pending is None
        tr = S['trend']
        # ---------- zone invalidated by an entry-timeframe close beyond it
        if p['ltfInv']:
            for z in zones:
                if (z['kind'] == 1 and c < z['bot'] - p['ltfK'] * at15[i]) or (z['kind'] == -1 and c > z['top'] + p['ltfK'] * at15[i]):
                    z['nb'] = z.get('nb', 0) + 1
                elif not p['ltfAny']:
                    z['nb'] = 0
                if z.get('nb', 0) >= p['ltfN']:
                    z['dead'] = True
                    if arm['dir'] != 0 and arm.get('zid') == z['id'] and pending is None and pos is None: arm = dict(dir=0)
        # ---------- arming
        if i >= 1:
            if flat and arm['dir'] == 0 and tr != 0 and not inWeek and not isRange:
                if p['useZones']:
                    for z in zones:
                        ok = not (p['oneUse'] and z['used']) and not z.get('dead') and (not p['maxTouch'] or z.get('touch', 0) < p['maxTouch']) and (not p['minZW'] or A is None or (z['top'] - z['bot']) >= p['minZW'] * A['ATR']) and (not p['maxAgeD'] or (t - z['t']) / 86400 <= p['maxAgeD'])
                        if ok and z['kind'] == 1 and tr == 1 and l <= z['top'] and b15[i - 1][3] > z['top'] and c > z['bot'] - p['invK'] * at15[i] * 4:
                            z['touch']=z.get('touch',0)+1; arm = dict(dir=1, src='zone' if z['tf'] == 1 else 'big zone', zt=z['top'], zb=z['bot'], zid=z['id'], zfl=z['fl'], zt0=z['t'], ztouch=z['touch']); break
                        if ok and z['kind'] == -1 and tr == -1 and h >= z['bot'] and b15[i - 1][2] < z['bot'] and c < z['top'] + p['invK'] * at15[i] * 4:
                            z['touch']=z.get('touch',0)+1; arm = dict(dir=-1, src='zone' if z['tf'] == 1 else 'big zone', zt=z['top'], zb=z['bot'], zid=z['id'], zfl=z['fl'], zt0=z['t'], ztouch=z['touch']); break
                if p['useLines'] and arm['dir'] == 0 and A is not None:
                    tol = 0.1 * A['ATR']
                    if S['u'] is not None and tr == 1 and S['uN'] == 2:
                        uv = lineAt(*S['u'], t); uv1 = lineAt(*S['u'], b15[i - 1][0])
                        if l <= uv + tol and b15[i - 1][3] > uv1 + tol and c > uv - tol:
                            arm = dict(dir=1, src='line', zid=None)
                    if S['d'] is not None and tr == -1 and S['dN'] == 2:
                        dv = lineAt(*S['d'], t); dv1 = lineAt(*S['d'], b15[i - 1][0])
                        if h >= dv - tol and b15[i - 1][2] < dv1 - tol and c < dv + tol:
                            arm = dict(dir=-1, src='line', zid=None)
                if arm['dir'] != 0:
                    arm.update(bar=i, time=t, ext=l if arm['dir'] == 1 else h, struct=False, sw='')
                    if p['alertMode']: events.append(dict(kind='watch', t=t, dir=arm['dir'], arm=dict(arm), trend=tr, lastHi=S['lastHi'], lastLo=S['lastLo']))
            elif arm['dir'] != 0:
                arm['ext'] = min(arm['ext'], l) if arm['dir'] == 1 else max(arm['ext'], h)
        # ---------- track a 15m close beyond the far side of the armed zone, and a close back out on the trade side
        if arm['dir'] != 0 and arm.get('zt') is not None:
            if arm['dir'] == 1:
                if c < arm['zb']: arm['br'] = True
                if arm.get('br') and c > arm['zt']: arm['rc'] = True
            else:
                if c > arm['zt']: arm['br'] = True
                if arm.get('br') and c < arm['zb']: arm['rc'] = True
        # ---------- entry
        why = ''
        if flat and arm['dir'] != 0 and i > arm['bar']:
            d = arm['dir']
            expired = i - arm['bar'] > p['maxWait'] or (d == 1 and tr != 1) or (d == -1 and tr != -1)
            cv = ctl(d, t); cv1 = ctl(d, b15[i - 1][0])
            pc = b15[i - 1][4]
            if d == 1:
                lastSw = hiP[-1] if hiP else None
                stp = arm['ext'] - 0.02 * at15[i]; risk = c - stp
                lb = cv is not None and c > cv and pc <= cv1
                bos = lastSw is not None and c > lastSw and pc <= lastSw
                wp = False
                if len(loP) >= 2 and A is not None:
                    l1, l2, t1, t2 = loP[-2], loP[-1], loT[-2], loT[-1]
                    if t1 >= arm['time'] - 4 * tfsec and abs(l2 - l1) <= p['wTolK'] * A['ATR'] and hiP:
                        nk = None
                        for j in range(len(hiP) - 1, -1, -1):
                            if t1 < hiT[j] < t2: nk = hiP[j]; break
                        if nk is not None and c > nk and pc <= nk: wp = True
                sig = (p['sigMode'] == 0 and bos) or wp
                if sig: arm['struct'] = True; arm['sw'] = 'W' if wp else 'BOS'
                if arm['struct']:
                    if sig and (cv is None or c > cv or cv - c > p['farR'] * risk): why = arm['sw']
                    elif lb: why = arm['sw'] + ' + red line'
                if why:
                    tgt = S['lastHi']
                    ret = (tgt - arm['ext']) / (tgt - S['lastLo']) if (tgt is not None and S['lastLo'] is not None and tgt > S['lastLo']) else 0
                    if tgt is not None and risk > 0 and p['tpCap'] and (tgt - c) / risk > p['tpCap']: tgt = c + p['tpCap'] * risk
                    if tgt is None or tgt - c < p['minRR'] * risk or risk <= 0 or not ma_ok(1, i) or (p['maxRR'] and (tgt - c) / risk > p['maxRR']) or (p['maxRet'] and ret > p['maxRet']):
                        why = ''; arm['dir'] = 0
            else:
                lastSw = loP[-1] if loP else None
                stp = arm['ext'] + 0.02 * at15[i]; risk = stp - c
                lb = cv is not None and c < cv and pc >= cv1
                bos = lastSw is not None and c < lastSw and pc >= lastSw
                mp = False
                if len(hiP) >= 2 and A is not None:
                    h1, h2, t1, t2 = hiP[-2], hiP[-1], hiT[-2], hiT[-1]
                    if t1 >= arm['time'] - 4 * tfsec and abs(h2 - h1) <= p['wTolK'] * A['ATR'] and loP:
                        nk = None
                        for j in range(len(loP) - 1, -1, -1):
                            if t1 < loT[j] < t2: nk = loP[j]; break
                        if nk is not None and c < nk and pc >= nk: mp = True
                sig = (p['sigMode'] == 0 and bos) or mp
                if sig: arm['struct'] = True; arm['sw'] = 'M' if mp else 'BOS'
                if arm['struct']:
                    if sig and (cv is None or c < cv or c - cv > p['farR'] * risk): why = arm['sw']
                    elif lb: why = arm['sw'] + ' + red line'
                if why:
                    tgt = S['lastLo']
                    ret = (arm['ext'] - tgt) / (S['lastHi'] - tgt) if (tgt is not None and S['lastHi'] is not None and S['lastHi'] > tgt) else 0
                    if tgt is not None and risk > 0 and p['tpCap'] and (c - tgt) / risk > p['tpCap']: tgt = c - p['tpCap'] * risk
                    if tgt is None or c - tgt < p['minRR'] * risk or risk <= 0 or not ma_ok(-1, i) or (p['maxRR'] and (c - tgt) / risk > p['maxRR']) or (p['maxRet'] and ret > p['maxRet']):
                        why = ''; arm['dir'] = 0
            if why == '' and expired and arm['dir'] != 0:
                arm['dir'] = 0
        if why and arm['dir'] != 0 and arm.get('zt') is not None:
            nearOK = (c > arm['zt']) if arm['dir'] == 1 else (c < arm['zb'])
            if p['reclaim'] and arm.get('br') and not arm.get('rc'): why = ''
            if p['nearAlways'] and not nearOK: why = ''
        if why and arm['dir'] != 0 and p['alertMode']:
            events.append(dict(kind='setup', t=t, dir=arm['dir'], why=why, entry=c, stop=stp, tp=tgt, risk=abs(c - stp), arm=dict(arm, ret=ret)))
            arm = dict(dir=0); why = ''
        if why and arm['dir'] != 0:
            pending = dict(dir=arm['dir'], stop=stp, tp=tgt, rk=abs(c - stp), why=why, src=arm['src'], sigT=t, sigClose=c, arm=dict(arm, ret=ret), atr4=A['ATR'] if A else None, trend=tr, dT=S['dTrend'], lastHi=S['lastHi'], lastLo=S['lastLo'], prevHi=S['prevHi'], prevLo=S['prevLo'], w=(loP[-2],loP[-1],loT[-2],loT[-1]) if arm['dir']==1 and len(loP)>1 else ((hiP[-2],hiP[-1],hiT[-2],hiT[-1]) if len(hiP)>1 else None))
            if p['oneUse'] and arm.get('zid'):
                for z in zones:
                    if z['id'] == arm['zid']: z['used'] = True
            arm = dict(dir=0)
        # trailing stop update for modes 3/4 (Pine updates exit each bar)
        if pos is not None and p['partMode'] >= 3 and pos['trail']:
            if pos['dir'] == 1 and loP and loP[-1] > pos['curStop']: pos['curStop'] = loP[-1]
            if pos['dir'] == -1 and hiP and hiP[-1] < pos['curStop']: pos['curStop'] = hiP[-1]
        if pos is not None and p['beR'] and not pos.get('be'):
            fav = (h - pos['entry']) if pos['dir'] == 1 else (pos['entry'] - l)
            if fav >= p['beR'] * pos['rk']:
                pos['be'] = True; pos['curStop'] = pos['entry'] + (0 if pos['dir'] == 1 else 0)
        if pos is not None and p['partMode'] == 4:
            pos['tp'] = None
        if A is not None: aT_prev = A['T'] if newA else aT_prev
        prevA = A['T'] if A is not None else prevA
        prevB = B['T'] if B is not None else prevB
        prevW = Wp['T'] if Wp is not None else prevW
    return events if p['alertMode'] else trades

def summary(tr):
    R = [x['R'] for x in tr]
    return dict(n=len(R), w=sum(r > 0 for r in R), sum=round(sum(R), 2))
