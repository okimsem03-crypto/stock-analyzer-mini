"""📈 누적 승률 — 추천일 기준으로 오늘추천 · 초단기 · 도전주 등 ‘추천’의 성과를 한 곳에서 관리 (참고 자료 · 투자 권유 아님)

[무엇을 보여주나요]
  · 추천 종류별 요약(건수 · 승률 · 수익 비율 · 평균 수익률 · 최근 20건 승률)
  · 추천일 기준 누적 승률 꺾은선(추천이 쌓일수록 승률이 어떻게 변하는지)
  · 추천일별 표(그날 추천한 종목들의 승률·평균 수익률, 눌러서 종목별 결과 확인)

[승률 정의 — 종류마다 달라서 화면에도 적어 둬요]
  · 오늘추천(AI)   만기(단기 7일·중기 30일·장기 90일)가 지나 ‘확정’된 추천 중 +1% 이상으로 끝난 비율 (진행 중인 건은 승률에서 빼고 현재 수익률만 보여요)
  · 초단기 당일     시가에 샀다고 가정했을 때 당일 안에 목표(손절폭 1배)에 먼저 닿은 비율 (같은 날 손절·목표 둘 다면 손절로 계산)
  · 초단기 2영업일  2영업일 안에 목표(손절폭 2배)에 먼저 닿은 비율
  · 도전주          추천가 대비 현재가가 오른 비율 (만기 개념이 없어 ‘현재 기준’이고 확정이 아니에요)
  ‘수익 비율’은 종류와 상관없이 수익률이 0보다 큰 건의 비율이에요.

[새 추천 종류 추가] 다른 메뉴 모듈이 register_source(id, label, desc, win_def, fn) 로 등록하면 같은 화면에 자동으로 나와요.
  fn(days, opts) → [{"date","ticker","name","ret"(%,없으면 None),"win"(True/False/None),"settled"(bool),"tag"(구분 글자)}]
"""
import time
from datetime import timedelta

from flask import Blueprint, request
from menu_ctx import C

bp = Blueprint("winrate", __name__)
MENU = "winrate"

_CORE_FUNCS = ("_admin_json", "_admin_deny", "_alog", "_dbx", "_now_kst")
for _n in _CORE_FUNCS:
    globals()[_n] = (lambda n: (lambda *a, **k: getattr(C, n)(*a, **k)))(_n)

SOURCES = []                 # {"id","label","desc","win_def","fn","color"}
COLORS = ["#2563eb", "#d97706", "#7c3aed", "#059669", "#db2777", "#0891b2"]


def register_source(sid, label, desc, win_def, fn):
    if any(s["id"] == sid for s in SOURCES):
        return
    SOURCES.append({"id": sid, "label": label, "desc": desc, "win_def": win_def, "fn": fn, "color": COLORS[len(SOURCES) % len(COLORS)]})


def _f(v, d=None):
    try:
        if v is None or v == "":
            return d
        return float(v)
    except Exception:
        return d


def _gw():
    return bool(request.environ.get("mini.gateway"))


# ══════════════════════════════════════════════════════════════
# 추천 종류별 자료 모으기 — 각 함수는 읽기 전용(표가 없으면 빈 목록)
# ══════════════════════════════════════════════════════════════
def _cut(days):
    return (_now_kst() - timedelta(days=days)).strftime("%Y-%m-%d") if days else "0000-00-00"


def src_daily(days, opts):
    """오늘추천(AI 선정) — 만기 확정건만 승패가 있고, 진행 중인 건은 현재 수익률만."""
    try:
        import menu_daily as D
        rows = D._track_rows(max(days, 30) if days else 3650)
    except Exception:
        return []
    live = opts.get("live") or {}
    out = []
    for t in rows:
        if t["date"] < _cut(days):
            continue
        settled = t.get("outcome") in ("win", "lose", "flat")
        px = t.get("eval_price") if settled else (live.get(t["ticker"]) or t.get("eval_price"))
        ret = round((px / t["pick_price"] - 1) * 100, 2) if px and t.get("pick_price") else None
        out.append({"date": t["date"], "ticker": t["ticker"], "name": t["name"], "ret": ret, "win": (t["outcome"] == "win") if settled else None,
                    "settled": settled, "tag": t.get("horizon") or "미분류"})
    return out


def _scalp_rows(days, ref):
    try:
        rows = _dbx("SELECT scalp_date,ticker,name,main,o_next,c_next,result,c2,res2 FROM dly_scalp WHERE result NOT IN ('','nodata') AND scalp_date>=? ORDER BY scalp_date DESC, rk",
                    (_cut(days),), fetch=True) or []
    except Exception:
        return []
    return [r for r in rows if ref or int(r[3] or 0) == 1]


def src_scalp_day(days, opts):
    out = []
    for d, tk, nm, main, o, c, r0, c2, r2 in _scalp_rows(days, opts.get("ref")):
        o, c = _f(o), _f(c)
        if not o or not c:
            continue
        out.append({"date": str(d), "ticker": tk, "name": nm, "ret": round((c / o - 1) * 100, 2), "win": r0 == "win", "settled": True, "tag": "★" if int(main or 0) else "참고"})
    return out


def src_scalp_two(days, opts):
    out = []
    for d, tk, nm, main, o, c, r0, c2, r2 in _scalp_rows(days, opts.get("ref")):
        o, c2 = _f(o), _f(c2)
        if not o or not c2 or not r2 or r2 == "nodata":
            continue
        out.append({"date": str(d), "ticker": tk, "name": nm, "ret": round((c2 / o - 1) * 100, 2), "win": r2 == "win", "settled": True, "tag": "★" if int(main or 0) else "참고"})
    return out


def src_challenge(days, opts):
    """도전주 — 추천가 대비 현재가. 만기가 없어 확정이 아니다(승률 칸은 ‘현재 기준’)."""
    try:
        import menu_challenge as CH
    except Exception:
        return []
    today = _now_kst().strftime("%Y-%m-%d")
    cond, args = "t.pick_date < ? AND t.pick_date >= ?", (today, _cut(days))
    sel = "t.pick_date,t.ticker,t.name,t.signals,t.grade,t.pick_price"
    rows, _i = CH._try(
        (f"SELECT {sel},COALESCE(d.price,s.price) FROM challenge_pick_track t LEFT JOIN challenge_dd_cache d ON d.ticker=t.ticker LEFT JOIN stock_price_cache s ON s.ticker=t.ticker WHERE {cond}", args),
        (f"SELECT {sel},d.price FROM challenge_pick_track t LEFT JOIN challenge_dd_cache d ON d.ticker=t.ticker WHERE {cond}", args),
        (f"SELECT {sel},s.price FROM challenge_pick_track t LEFT JOIN stock_price_cache s ON s.ticker=t.ticker WHERE {cond}", args),
        (f"SELECT {sel},NULL FROM challenge_pick_track t WHERE {cond}", args))
    live = opts.get("live") or {}
    out = []
    for d, tk, nm, sig, g, pp, cp in rows or []:
        if CH.SENTINEL not in str(sig or ""):
            continue                      # 예전 ‘도전점수’ 방식 기록은 뜻이 달라 뺀다(도전주 성과 화면과 같은 규칙)
        tk = str(tk).upper()
        pp, cp = _f(pp), _f(live.get(tk)) or _f(cp)
        ret = round((cp / pp - 1) * 100, 2) if pp and cp and pp > 0 and cp > 0 else None
        out.append({"date": str(d)[:10], "ticker": tk, "name": nm or "", "ret": ret, "win": (ret > 0) if ret is not None else None, "settled": False, "tag": (g or "-")})
    return out


# ══════════════════════════════════════════════════════════════
# 집계
# ══════════════════════════════════════════════════════════════
def _avg(xs):
    return round(sum(xs) / len(xs), 2) if xs else None


def _rate(a, b):
    return round(a / b * 100, 1) if b else None


def summarize(recs, current_basis=False):
    """current_basis=True 면(도전주) 확정 개념이 없으니 수익 여부가 승패."""
    ev = [r for r in recs if r["win"] is not None and (r["settled"] or current_basis)]
    rets = [r["ret"] for r in recs if r["ret"] is not None]
    wins = sum(1 for r in ev if r["win"])
    ev_sorted = sorted(ev, key=lambda r: (r["date"], r["ticker"]), reverse=True)[:20]
    return {"n": len(recs), "settled": len(ev), "win": wins, "win_rate": _rate(wins, len(ev)), "up_rate": _rate(sum(1 for x in rets if x > 0), len(rets)),
            "avg": _avg(rets), "recent": _rate(sum(1 for r in ev_sorted if r["win"]), len(ev_sorted)), "recent_n": len(ev_sorted), "open": len(recs) - len(ev)}


def by_date(recs, current_basis=False):
    g = {}
    for r in recs:
        g.setdefault(r["date"], []).append(r)
    out = []
    for d in sorted(g, reverse=True):
        s = summarize(g[d], current_basis)
        s["date"] = d
        out.append(s)
    return out


def cumulative(recs, current_basis=False):
    g = {}
    for r in recs:
        if r["win"] is not None and (r["settled"] or current_basis):
            g.setdefault(r["date"], []).append(r)
    pts, w, n = [], 0, 0
    for d in sorted(g):
        w += sum(1 for r in g[d] if r["win"])
        n += len(g[d])
        pts.append({"date": d, "rate": round(w / n * 100, 1), "n": n})
    return pts


def _live_for(tickers):
    try:
        import menu_daily as D
        lp = D.live_prices(list(dict.fromkeys(tickers))[:80])
        return {t: v[0] for t, v in lp.items() if v and v[0]}
    except Exception:
        return {}


def build_state(days, ref, with_live=True):
    sources = [dict(s) for s in SOURCES]
    # 진행 중 종목(오늘추천 미확정·도전주)의 현재가는 한 번에 모아서 조회
    live = {}
    if with_live:
        need = []
        try:
            import menu_daily as D
            need += [t["ticker"] for t in D._track_rows(365)[:80] if t.get("outcome") not in ("win", "lose", "flat")]
        except Exception:
            pass
        try:
            import menu_challenge as CH
            rows, _ = CH._try(("SELECT ticker FROM challenge_pick_track ORDER BY pick_date DESC LIMIT 60", ()))
            need += [str(r[0]).upper() for r in rows or []]
        except Exception:
            pass
        live = _live_for(need) if need else {}
    opts = {"ref": ref, "live": live}
    out = []
    for i, s in enumerate(sources):
        try:
            recs = s["fn"](days, opts)
        except Exception as e:
            print(f"[누적승률] {s['id']} 집계 오류(무시): {type(e).__name__}: {e}")
            recs = []
        cb = s["id"] == "challenge"
        recs.sort(key=lambda r: (r["date"], r["ticker"]), reverse=True)
        out.append({"id": s["id"], "label": s["label"], "desc": s["desc"], "win_def": s["win_def"], "color": s["color"], "current_basis": cb,
                    "summary": summarize(recs, cb), "by_date": by_date(recs, cb)[:120], "cum": cumulative(recs, cb), "records": recs[:600]})
    return {"ok": True, "days": days, "ref": ref, "at": _now_kst().strftime("%Y-%m-%d %H:%M"), "sources": out}


# ══════════════════════════════════════════════════════════════
# API
# ══════════════════════════════════════════════════════════════
def _days_arg():
    try:
        d = int(request.args.get("days", "90"))
    except Exception:
        d = 90
    return d if d in (30, 90, 180, 365, 0) else 90


@bp.route("/admin/api/winrate/state", methods=["GET"])
def api_state():
    deny = _admin_deny()
    if deny:
        return deny
    return _admin_json(build_state(_days_arg(), request.args.get("ref") == "1", with_live=request.args.get("live") != "0"))


@bp.route("/admin/api/winrate/refresh", methods=["POST"])
def api_refresh():
    """결과 갱신 — 초단기 지난 후보의 당일·2영업일 결과를 가져오고, 오늘추천 만기 평가를 확정한다(관리자만)."""
    deny = _admin_deny(write=True)
    if deny or _gw():
        return deny or _admin_json({"error": "관리자만 쓸 수 있어요."}, 403)
    notes = []
    try:
        import menu_scalp as S
        done, wait = S.evaluate_pending()
        notes.append(f"초단기 {done}건 확인" + (f"({wait}건 대기)" if wait else ""))
    except Exception as e:
        notes.append("초단기 갱신 실패: " + str(e)[:40])
    try:
        import menu_daily as D
        D.api_track()                      # 만기가 지난 오늘추천을 그 시점 가격으로 확정(원래 [지난 추천 성과]가 하던 일)
        notes.append("오늘추천 만기 평가 반영")
    except Exception as e:
        notes.append("오늘추천 갱신 실패: " + str(e)[:40])
    _alog("winrate_refresh", " · ".join(notes))
    st = build_state(_days_arg(), request.args.get("ref") == "1")
    st["notes"] = notes
    return _admin_json(st)


# ══════════════════════════════════════════════════════════════
# 화면
# ══════════════════════════════════════════════════════════════
TAB_JS = r"""
var WR={days:90,ref:false,st:null,src:'',busy:false};
function wrSt(n,css){n.style.cssText=css;return n}
function wrFmt(v,suf){return v==null?'-':(v+(suf||''))}
function wrRet(v){return v==null?'-':((v>0?'+':'')+v.toFixed(2)+'%')}
function wrCol(v){return v==null?'#64748b':(v>0?'#e11d48':(v<0?'#2563eb':'#64748b'))}
function wrLoad(p){p.innerHTML='';var box=el('div');box.id='wrBox';p.appendChild(box);
 if(MEMBER_MODE&&!ftOk('view')){var c=el('div','c');c.appendChild(el('b',null,'📈 누적 승률'));c.appendChild(el('div','note','추천일 기준 승률을 모아 보여주는 화면이에요. 참고 자료이며 투자 권유가 아니에요.'));box.appendChild(c);ftSec(c,'view');return}
 wrDraw();wrFetch()}
function wrFetch(refresh){var u='/admin/api/winrate/'+(refresh?'refresh':'state')+'?days='+WR.days+'&ref='+(WR.ref?1:0);
 var h=$('wrStat');if(h)h.textContent='⏳ 불러오는 중…';
 var pr=refresh?apiJ(u,{}):api(u);
 return pr.then(function(j){if(j.error){toast('⚠ '+j.error);return}WR.st=j;if(refresh)toast('✅ 결과를 갱신했어요 — '+(j.notes||[]).join(' · '));wrDraw()},function(){toast('⚠ 불러오지 못했어요')})}
function wrDraw(){var p=$('wrBox');if(!p)return;p.innerHTML='';
 var hd=el('div','c');wrSt(hd,'background:linear-gradient(135deg,#0a1228,#1b2f66);color:#fff;border:0');
 hd.appendChild(wrSt(el('div',null,'📈 누적 승률 — 추천일 기준'),'font-size:20px;font-weight:900'));
 hd.appendChild(wrSt(el('div',null,'오늘추천·초단기·도전주 등 추천한 날을 기준으로 승률과 평균 수익률을 쌓아서 보여줘요. 승률의 뜻은 종류마다 달라서 아래 카드에 적어 두었어요. 참고 자료이며 투자 권유가 아니에요.'),'font-size:13px;opacity:.9;margin-top:6px;line-height:1.6'));
 var r=el('div');wrSt(r,'margin-top:12px;display:flex;gap:8px;flex-wrap:wrap;align-items:center');
 [[30,'30일'],[90,'90일'],[180,'180일'],[365,'1년'],[0,'전체']].forEach(function(o){var b=bt(o[1],WR.days===o[0]?'bt':'bt3',function(){WR.days=o[0];wrFetch()});r.appendChild(b)});
 var lb=el('label');wrSt(lb,'font-size:12.5px;color:#e2e8f0;margin-left:8px');var cb=el('input');cb.type='checkbox';cb.checked=WR.ref;cb.onchange=function(){WR.ref=cb.checked;wrFetch()};lb.appendChild(cb);lb.appendChild(document.createTextNode(' 초단기 참고 순위(★ 밖)도 포함'));r.appendChild(lb);
 r.appendChild(adm(bt('🔄 결과 갱신','bt2',function(){wrFetch(true)})));hd.appendChild(r);
 var s=el('div','m');s.id='wrStat';wrSt(s,'color:#cbd5e1;margin-top:6px');s.textContent=WR.st?('기준 시각 '+WR.st.at):'';hd.appendChild(s);p.appendChild(hd);
 if(!WR.st){p.appendChild(el('div','c','⏳ 불러오는 중…'));return}
 var S=WR.st.sources;
 var cards=el('div');wrSt(cards,'display:grid;grid-template-columns:repeat(auto-fit,minmax(250px,1fr));gap:10px;margin:10px 0');
 S.forEach(function(x){var m=x.summary,c=el('div','c');wrSt(c,'margin:0;border-top:4px solid '+x.color);
  c.appendChild(wrSt(el('b',null,x.label),'font-size:15px'));
  var big=el('div');wrSt(big,'display:flex;align-items:baseline;gap:8px;margin-top:6px');var rt=el('span',null,m.win_rate==null?'-':m.win_rate+'%');wrSt(rt,'font-size:30px;font-weight:900;color:'+x.color);big.appendChild(rt);
  big.appendChild(el('span','m',x.current_basis?'현재 기준 승률':'승률'));c.appendChild(big);
  c.appendChild(el('div','m','평가 '+m.settled+'건 중 '+m.win+'건 · 전체 '+m.n+'건'+(m.open&&!x.current_basis?' · 진행 중 '+m.open+'건':'')));
  var kv=el('div');wrSt(kv,'display:flex;gap:6px;flex-wrap:wrap;margin-top:8px');
  [['수익 비율',wrFmt(m.up_rate,'%')],['평균 수익률',wrRet(m.avg)],['최근 '+m.recent_n+'건 승률',wrFmt(m.recent,'%')]].forEach(function(k){var t=el('div');wrSt(t,'padding:6px 10px;border-radius:10px;background:#f1f5f9;min-width:70px');t.appendChild(wrSt(el('div',null,k[0]),'font-size:11px;color:#64748b'));t.appendChild(wrSt(el('div',null,k[1]),'font-size:14px;font-weight:800'));kv.appendChild(t)});c.appendChild(kv);
  var d=el('div','note','승률 기준: '+x.win_def);c.appendChild(d);cards.appendChild(c)});p.appendChild(cards);
 wrChart(p,S);wrTable(p,S)}
function wrChart(p,S){var c=el('div','c');c.appendChild(wrSt(el('b',null,'추천일 기준 누적 승률'),'font-size:15px'));
 c.appendChild(el('div','note','추천한 날짜 순서대로 확정된 건을 계속 더해 계산한 승률이에요. 선이 평평해질수록 표본이 쌓여 믿을 만해져요(건수가 적은 초반에는 크게 흔들려요).'));
 var all=[];S.forEach(function(x){x.cum.forEach(function(q){if(all.indexOf(q.date)<0)all.push(q.date)})});all.sort();
 if(all.length<2){c.appendChild(el('div','note','아직 그래프를 그릴 만큼 확정된 기록이 없어요. 결과가 쌓이면 나와요.'));p.appendChild(c);return}
 var NS='http://www.w3.org/2000/svg',W=760,H=260,L=40,R=12,T=14,B=28;var svg=document.createElementNS(NS,'svg');svg.setAttribute('viewBox','0 0 '+W+' '+H);svg.setAttribute('width','100%');svg.setAttribute('role','img');svg.setAttribute('aria-label','추천일 기준 누적 승률 꺾은선 그래프');wrSt(svg,'max-width:100%;height:auto;margin-top:6px');
 function X(i){return L+(W-L-R)*(all.length===1?0:i/(all.length-1))}function Y(v){return T+(H-T-B)*(1-v/100)}
 function ln(x1,y1,x2,y2,col,w,dash){var e=document.createElementNS(NS,'line');e.setAttribute('x1',x1);e.setAttribute('y1',y1);e.setAttribute('x2',x2);e.setAttribute('y2',y2);e.setAttribute('stroke',col);e.setAttribute('stroke-width',w||1);if(dash)e.setAttribute('stroke-dasharray',dash);svg.appendChild(e)}
 function tx(x,y,t,anc){var e=document.createElementNS(NS,'text');e.setAttribute('x',x);e.setAttribute('y',y);e.setAttribute('font-size','11');e.setAttribute('fill','#64748b');if(anc)e.setAttribute('text-anchor',anc);e.textContent=t;svg.appendChild(e)}
 [0,25,50,75,100].forEach(function(v){ln(L,Y(v),W-R,Y(v),v===50?'#94a3b8':'#e2e8f0',1,v===50?'4 3':null);tx(L-6,Y(v)+4,v+'%','end')});
 tx(L,H-8,all[0].slice(2),'start');tx(W-R,H-8,all[all.length-1].slice(2),'end');
 S.forEach(function(x){if(!x.cum.length)return;var pts=[],last=null,k=0;
  all.forEach(function(d,i){while(k<x.cum.length&&x.cum[k].date<=d){last=x.cum[k];k++}if(last)pts.push([X(i),Y(last.rate)])});
  var pl=document.createElementNS(NS,'polyline');pl.setAttribute('points',pts.map(function(q){return q[0].toFixed(1)+','+q[1].toFixed(1)}).join(' '));pl.setAttribute('fill','none');pl.setAttribute('stroke',x.color);pl.setAttribute('stroke-width','2.5');pl.setAttribute('stroke-linejoin','round');svg.appendChild(pl);
  var q=pts[pts.length-1];if(q){var dot=document.createElementNS(NS,'circle');dot.setAttribute('cx',q[0]);dot.setAttribute('cy',q[1]);dot.setAttribute('r','4');dot.setAttribute('fill',x.color);svg.appendChild(dot);tx(Math.min(q[0]+6,W-R-30),Math.max(q[1]-8,T+10),last.rate+'%','start')}});
 c.appendChild(svg);var lg=el('div');wrSt(lg,'display:flex;gap:14px;flex-wrap:wrap;margin-top:4px;font-size:12.5px');
 S.forEach(function(x){var i=el('span');var sw=el('span');wrSt(sw,'display:inline-block;width:14px;height:4px;border-radius:2px;margin-right:5px;vertical-align:middle;background:'+x.color);i.appendChild(sw);i.appendChild(document.createTextNode(x.label+(x.cum.length?' ('+x.cum[x.cum.length-1].n+'건)':' (기록 없음)')));lg.appendChild(i)});c.appendChild(lg);p.appendChild(c)}
function wrTable(p,S){var c=el('div','c');c.appendChild(wrSt(el('b',null,'추천일별 승률'),'font-size:15px'));
 var bar=el('div');wrSt(bar,'margin:6px 0;display:flex;gap:6px;flex-wrap:wrap');
 [['','전체']].concat(S.map(function(x){return [x.id,x.label]})).forEach(function(o){bar.appendChild(bt(o[1],WR.src===o[0]?'bt':'bt3',function(){WR.src=o[0];wrDraw()}))});c.appendChild(bar);
 var rows=[];S.forEach(function(x){if(WR.src&&x.id!==WR.src)return;x.by_date.forEach(function(d){rows.push({x:x,d:d})})});rows.sort(function(a,b){return a.d.date<b.d.date?1:(a.d.date>b.d.date?-1:0)});
 if(!rows.length){c.appendChild(el('div','note','아직 기록이 없어요. 추천이 쌓이고 결과가 확정되면 여기에 나와요.'));p.appendChild(c);return}
 var tw=el('div');wrSt(tw,'overflow-x:auto');var t=el('table'),h=el('tr');['추천일','구분','건수','평가','승','승률','수익 비율','평균 수익률'].forEach(function(k){h.appendChild(el('th',null,k))});t.appendChild(h);
 rows.slice(0,150).forEach(function(o){var d=o.d,tr=el('tr');wrSt(tr,'cursor:pointer');tr.appendChild(el('td',null,d.date));var tdl=el('td',null,o.x.label);wrSt(tdl,'color:'+o.x.color+';font-weight:700');tr.appendChild(tdl);
  tr.appendChild(el('td',null,d.n));tr.appendChild(el('td',null,d.settled));tr.appendChild(el('td',null,d.win));
  var wr=el('td',null,d.win_rate==null?'-':d.win_rate+'%');wrSt(wr,'font-weight:800');tr.appendChild(wr);tr.appendChild(el('td',null,wrFmt(d.up_rate,'%')));
  var av=el('td',null,wrRet(d.avg));wrSt(av,'color:'+wrCol(d.avg)+';font-weight:700');tr.appendChild(av);t.appendChild(tr);
  var open=false,dt=null;tr.onclick=function(){open=!open;if(!open){if(dt&&dt.parentNode)dt.parentNode.removeChild(dt);return}
   dt=el('tr');var td=el('td');td.colSpan=8;wrSt(td,'background:#f8fafc;padding:6px 10px');
   o.x.records.filter(function(r){return r.date===d.date}).forEach(function(r){var l=el('div');wrSt(l,'font-size:12.5px;line-height:1.7');var st=r.settled||o.x.current_basis?(r.win?'🎯 승':'✖ 패'):'진행 중';
    l.appendChild(document.createTextNode(r.name+' ('+r.ticker+') · '+r.tag+' · '+st+' · '));var rv=el('b',null,wrRet(r.ret));rv.style.color=wrCol(r.ret);l.appendChild(rv);
    var a=el('a',null,'  📈');a.href='/?t='+r.ticker;a.target='_blank';a.rel='noopener';l.appendChild(a);td.appendChild(l)});
   dt.appendChild(td);tr.parentNode.insertBefore(dt,tr.nextSibling)}});
 tw.appendChild(t);c.appendChild(tw);c.appendChild(el('div','note','줄을 누르면 그날 추천한 종목별 결과가 펼쳐져요. 수익률은 ‘오늘추천: 추천가→확정(또는 현재가)’, ‘초단기: 시가→당일 종가(또는 2영업일 종가)’, ‘도전주: 추천가→현재가’ 기준이고 수수료·세금은 빠져 있어요.'));p.appendChild(c)}
"""


def _register_builtin_sources():
    register_source("daily", "오늘추천(AI)", "AI가 고른 추천 종목(단기·중기·장기 호흡)", "만기가 지난 확정 건 중 +1% 이상으로 끝난 비율(진행 중은 제외)", src_daily)
    register_source("scalp_day", "초단기 · 당일", "초단기(장전) ★ 후보를 시가에 샀다고 가정", "당일 안에 목표(손절폭 1배)에 먼저 닿은 비율(같은 날 손절·목표면 손절)", src_scalp_day)
    register_source("scalp_2d", "초단기 · 2영업일", "초단기(장전) ★ 후보, 2영업일 관점", "2영업일 안에 목표(손절폭 2배)에 먼저 닿은 비율", src_scalp_two)
    register_source("challenge", "도전주", "낙폭 회복 도전주 기록", "추천가보다 현재가가 오른 비율 — 만기가 없어 확정이 아니에요", src_challenge)


def register():
    _register_builtin_sources()
    C.register_menu({"id": MENU, "label": "누적 승률", "icon": "📈", "public_path": "/m/winrate", "admin_path": "/admin#wr",
                     "desc": "오늘추천·초단기·도전주 등 추천을 추천일 기준으로 모아 승률·평균 수익률·누적 승률 그래프를 보여줘요. 참고 자료이며 투자 권유가 아니에요.",
                     "access": "admin"})
    C.register_admin_tab("wr", "📈 누적 승률", TAB_JS, "wrLoad", menu=MENU)
    C.register_feature(MENU, "view", "누적 승률 보기", "추천 종류별 승률·평균 수익률·추천일별 결과·누적 승률 그래프(읽기 전용).", default="admin", endpoints=["/admin/api/winrate/state"])
    return bp
