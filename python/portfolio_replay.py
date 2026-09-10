"""Chronological, read-only replay of recorded US main-strategy evidence.

This is a displayed-liquidity simulation, not a reconstruction of exchange queue
priority. It never fills from a last-trade price or a future book snapshot.
"""
import heapq
import itertools
import math
from collections import Counter
from datetime import datetime, timezone
import fees_us
import trader
import signal_calibration
from execution_quality import entry_price, remaining_signal_margin, signal_freshness_problem


def iso(at):
    return datetime.fromtimestamp(at,timezone.utc).isoformat()


def levels(raw):
    def number(v):
        return float(v.get('value') if isinstance(v,dict) else v)
    out=[]
    for row in raw:
        p,q=number(row['px']),number(row['qty'])
        if not math.isfinite(p) or not math.isfinite(q) or not 0<p<1 or q<0:
            raise ValueError('Invalid book level')
        if q:
            out.append([p,q])
    return out


class Portfolio:
    def __init__(self,cfg,events,*,latency_ms=250,depth_fraction=1,slippage_cents=0,cancel_latency_ms=250):
        self.cfg=cfg
        self.start=float(cfg.get('main_paper_bankroll_usd',1000))
        self.cash=self.start
        self.latency=latency_ms/1000
        self.cancel_latency=cancel_latency_ms/1000
        self.depth_fraction=depth_fraction
        self.slip=slippage_cents/100
        self.books={}; self.meta={}; self.settled=set(); self.candidates={}
        self.positions=[]; self.orders=[]; self.trades=[]; self.curve=[]
        self.rejected=Counter(); self.evidence=Counter(); self.seen=set()
        self.seq=itertools.count(); self.heap=[]
        self.fees=0.; self.filled_orders=0; self.submitted=0
        self.peak=self.start; self.drawdown=0.; self.valuation_gaps=0
        self.day=None; self.day_start=self.start; self.breach_at=None
        self.realized=0.; self.daily_count=Counter()
        self.events=events
        self.calibration=None
        self.end=max((e['at'] for e in events),default=0)
        self.now=min((e['at'] for e in events),default=0)
        for e in events:
            self.push(e['at'],'evidence',e)
        if events:
            self.push(self.now,'scan',None)
            self.push(self.now,'poll',None)

    def push(self,at,kind,value):
        if at<=self.end:
            heapq.heappush(self.heap,(at,next(self.seq),kind,value))

    def book_levels(self,ticker,side,action):
        book=self.books.get(ticker)
        if not book or self.now-book['at']>5:
            return []
        key = ('offers' if side=='yes' else 'bids') if action=='buy' else ('bids' if side=='yes' else 'offers')
        return sorted([(r[0] if side=='yes' else 1-r[0],r) for r in book[key]],
                      key=lambda x:x[0],reverse=action=='sell')

    def quote(self,ticker,side):
        bids=self.book_levels(ticker,side,'sell'); asks=self.book_levels(ticker,side,'buy')
        return {'bid_cents':math.floor(bids[0][0]*100+1e-8) if bids else None,
                'ask_cents':math.ceil(asks[0][0]*100-1e-8) if asks else None}

    def mark(self,pos):
        remaining=pos['qty']; value=0.
        for price,row in self.book_levels(pos['ticker'],pos['side'],'sell'):
            qty=min(remaining,math.floor(row[1]))
            if qty>0:
                px=max(.01,price-self.slip)
                value+=qty*px-fees_us.fee(qty,px,self.now)
                remaining-=qty
            if remaining<=0:break
        return value,remaining

    def equity(self):
        total=self.cash; missing=0
        for pos in self.positions:
            if pos['qty']:
                value,left=self.mark(pos)
                total+=value; missing+=left
        return total,missing

    def mark_curve(self):
        equity,missing=self.equity()
        self.valuation_gaps+=bool(missing)
        self.peak=max(self.peak,equity)
        self.drawdown=min(self.drawdown,equity-self.peak)
        self.curve.append({'at':iso(self.now),'value':round(equity-self.start,4)})

    def reservation(self,order):
        return fees_us.reserved_cost(order['left'],order['limit'],self.now) if order['action']=='buy' and not order['done'] else 0

    def pending_for(self,pos):
        return any(not o['done'] and o['pos'] is pos for o in self.orders)

    def close_position(self,pos):
        if pos['qty'] or self.pending_for(pos) or pos['closed']:
            return
        pos['closed']=True
        if not pos['bought']:
            return
        self.trades.append({'ticker':pos['ticker'],'asset':pos['category'],'side':pos['side'],
            'costCents':100*pos['entry_cost']/pos['bought'],'contracts':pos['bought'],
            'minsLeft':None,'won':pos['pnl']>0,'pnlUsd':round(pos['pnl'],6),
            'at':iso(self.now),'event':pos['event'],'entryAt':iso(pos['entered'])})

    def submit(self,pos,action,qty,limit):
        order={'pos':pos,'action':action,'left':qty,'limit':limit,'done':False,'filled':False,'arrived':False}
        self.orders.append(order); self.submitted+=1
        self.push(self.now+self.latency,'arrival',order)
        # Cancel acknowledgement can race fills. Keep reservations until it arrives.
        ttl=float(self.cfg.get('order_expiration_sec',300))
        self.push(self.now+ttl+self.cancel_latency,'cancel',order)

    def fill(self,order):
        if order['done'] or not order['arrived']:return
        pos=order['pos']; action=order['action']; ticker=pos['ticker']
        if ticker in self.settled or not self.meta.get(ticker,{}).get('active',False):return
        for price,row in self.book_levels(ticker,pos['side'],action):
            px=price+self.slip if action=='buy' else price-self.slip
            if (action=='buy' and px>order['limit']+1e-9) or (action=='sell' and px<order['limit']-1e-9):break
            qty=min(order['left'],math.floor(row[1]))
            if action=='sell':qty=min(qty,pos['qty'])
            if qty<=0:continue
            charge=fees_us.fee(qty,px,self.now)
            if action=='buy':
                if qty*px+charge>self.cash+1e-8:break
                cost=qty*px+charge
                self.cash-=cost; pos['qty']+=qty; pos['cost']+=cost
                pos['entry_cost']+=cost; pos['bought']+=qty
            else:
                basis=pos['cost']*qty/pos['qty']
                proceeds=qty*px-charge
                pnl=proceeds-basis
                self.cash+=proceeds; pos['cost']-=basis; pos['qty']-=qty
                pos['pnl']+=pnl; self.realized+=pnl
            self.fees+=charge; row[1]-=qty; order['left']-=qty
            if not order['filled']:
                order['filled']=True; self.filled_orders+=1
            if not order['left']:
                order['done']=True
                break
        self.close_position(pos)
        self.mark_curve()

    def risk_blocked(self):
        offset=trader.trading_day_offset_min(self.cfg)
        day=datetime.fromtimestamp(self.now+offset*60,timezone.utc).date().isoformat()
        equity,_=self.equity()
        if day!=self.day:
            self.day=day; self.day_start=equity; self.breach_at=None
        pnl=equity-self.day_start
        sl=float(self.cfg.get('stop_loss_on_day',0)); tp=float(self.cfg.get('take_profit_on_day',0))
        breach=(sl<0 and pnl<=sl) or (tp>0 and pnl>=tp)
        if breach:
            if self.breach_at is None:self.breach_at=self.now
        else:self.breach_at=None
        daily=self.breach_at is not None and self.now-self.breach_at>=180
        lifetime=float(self.cfg.get('lifetime_loss_limit_usd',0)) or self.start*float(self.cfg.get('lifetime_loss_limit_pct',0))
        return daily or (lifetime>0 and -self.realized>=lifetime),daily and sl<0 and pnl<=sl

    def scan(self):
        blocked,_=self.risk_blocked()
        if blocked or trader._is_blocked_by_trading_hours(self.cfg,now=self.now)[0]:
            self.rejected['risk or trading hours']+=1
            return
        candidates=[]
        for key,(sig,source) in list(self.candidates.items()):
            if key in self.seen:continue
            if signal_freshness_problem(sig,float(self.cfg['max_signal_age_sec']),self.now):
                self.candidates.pop(key); self.rejected['expired signal']+=1; continue
            ok,why=trader.should_trade(sig,source,self.cfg,now=self.now)
            if not ok:
                self.rejected[why]+=1;continue
            candidates.append((key,sig,source))
        sides={}
        for _,s,source in candidates:
            sides.setdefault(s['ticker'],set()).add(trader._signal_cost_cents(s,source)[0])
        candidates.sort(key=lambda c:trader._compute_edge(c[1],c[2]),reverse=True)
        for key,sig,source in candidates:
            ticker=sig['ticker']; side,signal_cents=trader._signal_cost_cents(sig,source)
            if len(sides[ticker])>1:
                self.rejected['conflicting signals']+=1;continue
            meta=self.meta.get(ticker)
            if not meta or not meta.get('active') or ticker in self.settled:
                self.rejected['missing or inactive market metadata']+=1;continue
            active=[p for p in self.positions if p['qty'] or self.pending_for(p)]
            if len(active)>=int(self.cfg['max_open_positions']):
                self.rejected['open position cap']+=1;continue
            if not self.cfg.get('unlimited_daily_new_positions') and self.daily_count[self.day]>=int(self.cfg['max_daily_new_positions']):
                self.rejected['daily position cap']+=1;continue
            event=sig.get('event_ticker') or meta.get('event_ticker') or ticker
            if sum(p['event']==event for p in active)>=int(self.cfg['max_positions_per_event']):
                self.rejected['event concentration cap']+=1;continue
            # Same correlated-outcome grouping as live: series when the recorded
            # metadata supplies one, otherwise the event.
            group=str(meta.get('series_ticker') or '') or event
            if any(p['ticker']==ticker and p['side']==side for p in active):
                self.rejected['market already open']+=1;continue
            try:
                limit=entry_price(self.quote(ticker,side),signal_cents,self.cfg)
            except ValueError as exc:
                self.rejected[str(exc)]+=1;continue
            edge=remaining_signal_margin(trader._compute_edge(sig,source),signal_cents,limit)
            if self.cfg.get('sizing_mode') == 'kelly':
                if self.calibration is None or self.now-self.calibration['asof'] >= 300:
                    self.calibration=signal_calibration.fit(self.events,self.now)
                try:
                    edge=signal_calibration.calibrated_edge(sig,source,limit,self.now,self.calibration)
                except ValueError:
                    self.rejected['Kelly calibration unavailable']+=1;continue
            threshold=float(self.cfg['min_edge_pts_momentum' if source=='momentum' else 'min_edge_pts_whale'])
            if edge<max(0,threshold) or limit>self.cfg['max_entry_price_cents'] or limit<(1 if self.cfg.get('use_rules') else self.cfg['min_entry_price_cents']):
                self.rejected['execution margin or price cap']+=1;continue
            px=limit/100
            tick=float(meta.get('tick_size',.01))
            if tick<=0 or abs(px/tick-round(px/tick))>1e-7:
                self.rejected['invalid tick']+=1;continue
            filled=sum(p['cost'] for p in active)
            reserved=sum(self.reservation(o) for o in self.orders)
            fraction=float(self.cfg.get('max_group_exposure_fraction') or 0)
            group_budget=None
            if fraction>0:
                used=sum(p['cost'] for p in active if p.get('group')==group)
                group_budget=max(0.,(self.cash+filled)*fraction-used)
                if group_budget<=0:
                    self.rejected['related-outcome exposure cap']+=1;continue
            budget=trader.entry_budget(self.cash,filled,filled+reserved,edge,limit,self.cfg,
                                       group_budget_usd=group_budget)
            if budget<1 or self.cash<5:
                self.rejected['cash or exposure budget']+=1;continue
            qty=fees_us.affordable_contracts(budget,px,self.now)
            minimum=math.ceil(float(meta.get('min_size',1)))
            if qty<minimum:
                self.rejected['market minimum exceeds budget']+=1;continue
            pos={'ticker':ticker,'event':event,'group':group,'side':side,'category':sig.get('category') or source,
                 'qty':0,'cost':0.,'bought':0,'entry_cost':0.,'pnl':0.,'entered':self.now,'closed':False}
            self.positions.append(pos);self.seen.add(key);self.daily_count[self.day]+=1
            self.submit(pos,'buy',qty,px)

    def poll(self):
        _,flatten=self.risk_blocked()
        for pos in self.positions:
            if not pos['qty'] or self.pending_for(pos):continue
            bid=self.quote(pos['ticker'],pos['side'])['bid_cents']
            if bid is None:continue
            tp=float(self.cfg.get('take_profit_pct',0))
            take=tp>0 and pos['cost']>0 and (pos['qty']*bid/100-pos['cost'])/pos['cost']>=tp
            if take or (flatten and self.cfg.get('flatten_on_daily_stop')):
                self.submit(pos,'sell',pos['qty'],bid/100)
        self.mark_curve()

    def ingest(self,event):
        kind=event['kind']; ticker=event['ticker']; p=event['payload']
        self.evidence[kind]+=1
        if kind=='gap':
            self.books.clear()
            self.mark_curve()
        elif kind=='market':self.meta[ticker]=p
        elif kind=='book':
            try:
                book={'bids':levels(p.get('bids',[])),'offers':levels(p.get('offers',[])),'at':self.now}
                for side in ('bids','offers'):
                    for row in book[side]:row[1]*=self.depth_fraction
                self.books[ticker]=book
            except (ValueError,KeyError,TypeError):
                self.books.pop(ticker,None);self.evidence['invalid_book']+=1;return
            for order in self.orders:
                if order['pos']['ticker']==ticker:self.fill(order)
            self.mark_curve()
        elif kind=='signal':
            sig=dict(p['signal']);source=p['source']
            meta=self.meta.get(ticker,{})
            sig.setdefault('close_time',meta.get('close_time',''))
            self.candidates[(source,sig['id'])]=(sig,source)
        elif kind=='settlement' and ticker not in self.settled:
            payout=float(p['yes_payout'])
            if not 0<=payout<=1:raise ValueError('Invalid settlement')
            self.settled.add(ticker)
            for order in self.orders:
                if order['pos']['ticker']==ticker:order['done']=True
            for pos in self.positions:
                if pos['ticker']!=ticker:continue
                value=pos['qty']*(payout if pos['side']=='yes' else 1-payout)
                pnl=value-pos['cost'];self.cash+=value;self.realized+=pnl;pos['pnl']+=pnl
                pos['qty']=0;pos['cost']=0;self.close_position(pos)
            self.mark_curve()

    def run(self):
        while self.heap:
            self.now,_,kind,value=heapq.heappop(self.heap)
            if kind=='evidence':self.ingest(value)
            elif kind=='scan':
                self.scan();self.push(self.now+max(5,float(self.cfg['trade_scan_interval'])),'scan',None)
            elif kind=='poll':
                self.poll();self.push(self.now+max(5,float(self.cfg['position_poll_interval'])),'poll',None)
            elif kind=='arrival':value['arrived']=True;self.fill(value)
            elif kind=='cancel':value['done']=True;self.close_position(value['pos'])
        self.now=self.end
        if self.events:self.mark_curve()
        return self.report()

    def report(self):
        from replay import _summarize
        caveats=[
            'US portfolio replay uses recorded receipt times, shared entry gates and sizing, cash reservations and position/event/daily caps.',
            'Books are sampled at most once per second per market. Queue position and hidden liquidity are unknown. Passive touches and last trades never count as fills; no maker rebate is assumed.',
            'Fees use the dated US schedule and round per simulated price-level fill. Actual fill fragmentation can produce different rounding; volume rebates are excluded.',
            'Settlement cash is released when settlement was first observed. Recording gaps and stale or insufficient exit depth value the unpriced remainder at zero; this is a conservative valuation, not a verified liquidation price.',
            'Main-strategy replay starts flat and does not simulate other engines, manual trades, API outages or exchange order rejections. It is not proof of profitability.',
        ]
        result=_summarize(self.trades,0,self.evidence['signal'],caveats)
        equity,missing=self.equity() if self.events else (self.start,0)
        result.update(mode='portfolio',tStat=None,totalPnlUsd=round(equity-self.start,4),
            realizedPnlUsd=round(self.realized,4),cashUsd=round(self.cash,4),equityUsd=round(equity,4),
            startBankrollUsd=self.start,feesUsd=round(self.fees,4),
            maxDrawdownUsd=round(self.drawdown,4),openPositions=sum(p['qty']>0 for p in self.positions),
            pendingOrders=sum(not o['done'] for o in self.orders),reservedUsd=round(sum(self.reservation(o) for o in self.orders),4),
            submittedOrders=self.submitted,filledOrders=self.filled_orders,
            independentEvents=len({t['event'] for t in self.trades}),
            coverage=dict(self.evidence),rejections=dict(self.rejected),valuationGapSamples=self.valuation_gaps,
            equity=self.curve[::max(1,len(self.curve)//399)][-399:]+self.curve[-1:],
            assumptions={'latencyMs':self.latency*1000,'cancelLatencyMs':self.cancel_latency*1000,
                         'depthFraction':self.depth_fraction,'slippageCents':self.slip*100},
            dataStatus='recorded' if self.evidence['book'] and self.evidence['signal'] else 'insufficient_data')
        if result['dataStatus']=='insufficient_data':
            result['caveats'].insert(0,'Not enough recorded order-book evidence. Leave main data collection enabled with a connected US account. Older signal-only records cannot reconstruct historical fills.')
        return result


def replay(cfg,events,**options):
    for name,low,high in [('latency_ms',0,60000),('cancel_latency_ms',0,60000),('depth_fraction',.01,1),('slippage_cents',0,10)]:
        if name in options and (not math.isfinite(float(options[name])) or not low<=float(options[name])<=high):
            raise ValueError('Invalid replay assumption: '+name)
    return Portfolio(cfg,events,**options).run()
