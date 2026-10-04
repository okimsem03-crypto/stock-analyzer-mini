"""종목분석 미니 — 공통 디자인 스킨(v166)
   · MAIN_CSS  : 메인 화면(HTML_TEMPLATE) 뒤에 덧붙이는 스킨 — 얇은 상단 바 + 왼쪽 사이드바 메뉴 + 컴팩트 카드
   · ADMIN_CSS : 관리자 콘솔·회원 메뉴 화면(ADMIN_APP_HTML) 스킨 — 왼쪽 사이드바 메뉴(내장 화면에서는 얇은 탭 줄)
   · SUB_CSS   : 도움말·개인정보처리방침 같은 단순 페이지의 상단 바 스킨
   색·모서리·그림자는 모두 여기 변수(:root)만 바꾸면 한꺼번에 바뀐다. 비밀값은 없다. """

TOKENS = """
:root{
  --navy:#0f2342; --navy2:#1a3763; --gold:#b98a2e;
  --ac:#2457d6; --ac2:#1b45b8; --acs:#eef3ff;
  --up:#e5384d; --down:#2f6bf2;
  --bg:#f5f6f9; --card:#ffffff; --border:#e4e7ee; --line2:#eef0f5;
  --text:#141b2b; --text2:#475266; --muted:#7a8497;
  --good:#16a34a; --warn:#d97706; --bad:#e5384d;
  --radius:12px; --sbw:224px; --chromeH:56px;
  --shadow:0 1px 2px rgba(15,35,66,.04);
}
"""

MAIN_CSS = TOKENS + r"""
/* ═══ v166 스킨 — 메인 화면 ═══ */
html{-webkit-text-size-adjust:100%}
body{font-size:13.5px; line-height:1.55; background:var(--bg); color:var(--text); font-feature-settings:"tnum" 1; letter-spacing:-.005em}
a{color:var(--ac)}

/* 상단 바 */
#chrome{position:sticky; top:0; z-index:60; background:#fff}
#admBar{background:var(--navy)!important; color:#e6ecf7!important; font-size:12px!important; padding:5px 16px!important; gap:8px!important; min-height:28px}
#admBar button{background:rgba(255,255,255,.14)!important; border-radius:6px!important; padding:3px 9px!important; font-size:11.5px!important}
#admBar a{font-size:12px}
.topbar{position:static!important; background:#fff; padding:0 16px; height:56px; min-height:56px; gap:10px; flex-wrap:nowrap;
  border-bottom:1px solid var(--border); box-shadow:none; align-items:center}
.brandBlock{flex:0 0 auto; flex-direction:row; align-items:baseline; gap:8px}
.brand{color:var(--navy); font-size:15.5px; font-weight:800; letter-spacing:-.02em; display:flex; align-items:baseline; gap:5px}
.brand span{color:var(--ac)}
.verTag{color:var(--muted)!important; font-size:10.5px!important; font-weight:600!important}
.sloganTag{display:none}
.searchWrap{flex:1 1 auto; max-width:480px; margin-left:12px}
.searchInput{background:#f1f3f8 url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='16' height='16' fill='none' stroke='%237a8497' stroke-width='2' stroke-linecap='round'%3E%3Ccircle cx='7' cy='7' r='5'/%3E%3Cpath d='M11 11l3.5 3.5'/%3E%3C/svg%3E") no-repeat 12px 50%;
  color:var(--text); border:1px solid transparent; border-radius:10px; padding:9px 14px 9px 36px; font-size:13.5px; height:38px}
.searchInput::placeholder{color:#8f98aa}
.searchInput:focus{background-color:#fff; border-color:var(--ac); box-shadow:0 0 0 3px rgba(36,87,214,.14)}
.searchDrop{border:1px solid var(--border); border-radius:12px; box-shadow:0 16px 40px -12px rgba(15,35,66,.28)}
.searchItem{padding:9px 14px; font-size:13px}
.tbActs{display:flex; align-items:center; gap:2px; margin-left:auto; flex:0 0 auto}
.refreshBtn{background:transparent!important; color:var(--text2)!important; font-size:12.5px; font-weight:600; padding:7px 10px; border-radius:8px; border:0}
.refreshBtn:hover{background:#f1f3f8!important; color:var(--navy)!important}
.blogBtn{background:#fff!important; color:var(--navy)!important; border:1px solid var(--border); font-size:12.5px; font-weight:700; padding:7px 12px; border-radius:8px; margin-left:6px}
.blogBtn:hover{border-color:var(--ac); color:var(--ac)!important}
#sbBtn{display:none; border:0; background:#f1f3f8; color:var(--navy); width:38px; height:38px; border-radius:10px; font-size:18px; cursor:pointer; flex:0 0 auto; font-family:inherit}
#sbBack{display:none}

/* 사이드바 메뉴 — 메뉴가 하나라도 보이면 켜짐(body.hasSb) */
.mainMenuBar{background:#fff; border:0; box-shadow:none}
body.hasSb{padding-left:var(--sbw)}
body.hasSb #chrome{margin-left:calc(var(--sbw) * -1)}
body.hasSb #mainMenuBar{position:fixed; left:0; top:var(--chromeH); bottom:0; width:var(--sbw); z-index:40; overflow-y:auto; overscroll-behavior:contain;
  border-right:1px solid var(--border); display:block!important}
body.hasSb .mmIn{display:block; max-width:none; padding:10px 10px 28px; margin:0}
.mmTitle{display:none}
.mmList{display:flex; flex-direction:column; gap:0; flex-wrap:nowrap}
.mmGrp{display:block; position:static; margin-top:4px}
.mmGi{display:flex; flex-direction:column; gap:1px; flex-wrap:nowrap; align-items:stretch}
.mmGb{display:flex; width:100%; max-width:none; align-items:center; justify-content:space-between; gap:6px; background:transparent!important; border:0!important;
  border-radius:6px; padding:10px 10px 5px; font-size:11px; font-weight:700; color:#8a93a6!important; letter-spacing:.06em; text-transform:none; cursor:pointer}
.mmGb:hover{color:var(--navy)!important}
.mmGb .mmDot{display:none!important}
.mmGb .mmGt{order:0; overflow:visible; text-overflow:clip}
.mmGb .mmCaret{font-size:9px; opacity:.55; order:1; transform:rotate(-90deg)!important}
.mmGrp.open .mmGb .mmCaret{transform:none!important}
.mmGrp.on .mmGb{background:transparent!important; color:var(--navy)!important}
.mmGrp.hasopen:not(.on) .mmGb{background:transparent!important}
.mmDd{display:none; position:static; min-width:0; max-width:none; padding:0; border:0; box-shadow:none; background:transparent; flex-direction:column; gap:1px; border-radius:0}
.mmGrp.open .mmDd{display:flex}
.mmGrp.r .mmDd{left:auto; right:auto}
.mmItem{display:flex; align-items:center; gap:9px; width:100%; padding:6px 10px; border:0!important; background:transparent!important; border-radius:8px;
  color:var(--text2)!important; font-size:13px; font-weight:500; text-decoration:none; position:relative; justify-content:flex-start}
.mmItem .ic{width:18px; text-align:center; font-size:14px; filter:grayscale(1); opacity:.7; flex:0 0 18px; line-height:1}
.mmItem .lb{flex:1 1 auto; min-width:0; overflow:hidden; text-overflow:ellipsis; white-space:nowrap}
.mmItem:hover{background:#f2f4f9!important; color:var(--navy)!important}
.mmItem.on{background:var(--acs)!important; color:var(--ac2)!important; font-weight:700}
.mmItem.on:hover{background:var(--acs)!important; color:var(--ac2)!important}
.mmItem.on .ic{filter:none; opacity:1}
.mmItem.on:before{content:""; position:absolute; left:-10px; top:7px; bottom:7px; width:3px; border-radius:0 3px 3px 0; background:var(--ac)}
.mmItem.open:not(.on){background:transparent!important}
.mmItem.hid{color:#8a6a1c!important}
.mmItem.hid .lb:after{content:"관리자"; margin-left:7px; font-size:9.5px; font-weight:700; padding:1px 6px; border-radius:999px; background:#f6ecd2; color:#8a6a1c; vertical-align:1px}
.mmItem .dot{order:3; margin-left:auto; width:6px; height:6px; background:var(--good); flex:0 0 6px}
.mmItem.nw .dot{background:var(--warn)}
.mmItem .tx{order:4; margin:0; padding:0 5px; font-size:13px; opacity:0}
.mmItem:hover .tx{opacity:.55}
.mmGrp[data-grp="main"]{margin-top:0}
.mmGrp[data-grp="admin"]{margin-top:10px; padding-top:10px; border-top:1px solid var(--line2)}
.mmGrp[data-grp="admin"] .mmGi{gap:1px}

/* 본문 영역 */
.wrap{max-width:1240px; padding:16px 22px 64px}
.tabHost{background:var(--bg)}
.tabHost iframe{background:var(--bg)}
.tabMsg{background:var(--navy); border-radius:8px; font-size:12.5px; top:70px; padding:7px 14px}
.empty{padding:60px 16px 36px; font-size:13px; line-height:1.8}
.empty .big{font-size:30px; margin-bottom:10px; opacity:.85}
.sloganLead{font-size:20px; font-weight:800; color:var(--navy); letter-spacing:-.03em; margin-bottom:6px}
.wakeNote{background:#fffaf0; border:1px solid #f3e3bd; border-radius:10px; font-size:11.5px; padding:9px 12px}
.demoBtn{background:var(--navy); border-radius:9px; padding:9px 18px; font-size:12.5px; font-weight:700}
.statsBadge{background:#fff; border-radius:8px; font-size:11.5px; padding:6px 12px}
.counterBadge{background:#fff; color:var(--text); border:1px solid var(--border); border-radius:10px; box-shadow:none; padding:8px 16px; font-size:12.5px}
.counterBadge .cbMain b{color:var(--navy); font-size:15px}
.counterBadge .cbSub{color:var(--muted); border-left-color:var(--border)}
.counterBadge .cbSub b{color:var(--text)}
.whyGrid{gap:10px; margin-top:28px}
.whyCard{padding:14px; border-radius:10px; box-shadow:none}
.whyIcon{font-size:20px; margin-bottom:6px; filter:grayscale(.4)}
.topBox,.recentBox{border-radius:10px}

/* 카드 */
.card{padding:14px 16px; margin-bottom:12px; border-radius:var(--radius); box-shadow:none}
.card h3{margin:0 0 10px; font-size:13px; font-weight:800; color:var(--navy); letter-spacing:-.01em}
.heroName{font-size:18px}
.heroPrice{font-size:26px; margin-top:8px}
.statGrid{gap:8px; grid-template-columns:repeat(auto-fill,minmax(128px,1fr))}
.statBox{background:#f7f8fb; border-radius:8px; padding:9px 11px}
.statLabel{font-size:10.5px; margin-bottom:3px}
.statVal{font-size:14.5px}
.vpBox,.peerItem,.vpNote{border-radius:8px}
.btn{border-radius:8px; padding:8px 13px; font-size:12.5px}
.btn-primary{background:var(--navy)}
.btn-ghost{background:#eef1f6}
.promptBox,.pasteBox{border-radius:8px; font-size:12px}
.aiPrimary{background:var(--ac); border-radius:10px; padding:12px 16px; font-size:15px; box-shadow:none}
.aiPrimary:hover{background:var(--ac2); filter:none}
.aiServiceBtn{border-radius:8px; padding:9px 13px}
.aiResult{background:#f9fafc; border:1px solid var(--border); border-radius:10px; padding:16px 18px; font-size:14px; line-height:1.85; color:var(--text)}
.aiResult .aiSection{font-size:14.5px; color:var(--navy); border-bottom:1px solid var(--border); margin:18px 0 8px}
.aiResult b{color:var(--navy)}
.aiResult .aiBullet::before{color:var(--ac)}
.ctaBanner{background:#fff; border:1px solid #ecdcae; border-left:3px solid var(--gold); border-radius:10px; box-shadow:none; animation:none; padding:12px 16px}
.ctaBanner:hover{transform:none; box-shadow:none; border-color:var(--gold)}
.ctaIcon{font-size:22px; filter:grayscale(.3)}
.ctaTitle{font-size:13.5px}.ctaSub{font-size:12px; color:#7a5a12}.ctaArrow{color:var(--gold)}
.voteCard{background:#fff; border:1px solid var(--border); border-radius:10px; padding:12px 14px}
.voteBtn{border-radius:8px; box-shadow:none; border:1px solid var(--border); font-size:13px; padding:8px 6px}
.tipBanner{border-radius:8px; padding:9px 13px}
.riskBanner{border-radius:10px; padding:13px 15px; border-width:1px}
.riskTitle{font-size:14px}
.badge{font-size:10px; padding:2px 8px}
.finTab{padding:5px 12px}
.finTable thead th{background:#f7f8fb}
.toast{background:var(--navy); border-radius:10px; font-size:12.5px}
.disclaimerCard{border-radius:14px}
.disclaimerHead{padding:16px 22px 14px}
.agreeBtn{background:var(--navy); border-radius:9px}
.cmtCard,.fl-card{border-radius:10px; box-shadow:none}

/* 최근 종목 패널(오른쪽) + 투표·댓글(본문 안으로) */
@media (min-width:1180px){
  .pageGrid{grid-template-columns:minmax(0,1fr) 260px; gap:16px}
  .recentSide{top:calc(var(--chromeH) + 14px); border-radius:var(--radius); box-shadow:none; padding:12px}
  .flRail{position:static!important; width:auto!important; max-height:none!important; overflow:visible!important; left:auto!important; bottom:auto!important; padding:0!important}
  .flRail .fl-card{box-shadow:none!important}
  body.flOn .wrap{padding-left:22px!important}
}
.rsTab.on{background:var(--navy); border-color:var(--navy)}
.rsItem{height:44px}
.rsFab{background:var(--navy); box-shadow:0 8px 22px rgba(15,35,66,.3)}

/* 태블릿·휴대폰: 사이드바 → 서랍(☰) */
@media (max-width:1023px){
  body.hasSb{padding-left:0}
  body.hasSb #chrome{margin-left:0}
  body.hasSb #sbBtn{display:inline-flex; align-items:center; justify-content:center}
  body.hasSb #mainMenuBar{top:0; width:264px; transform:translateX(-102%); transition:transform .2s ease; z-index:95; box-shadow:0 0 40px rgba(15,35,66,.28)}
  body.hasSb.sbOpen #mainMenuBar{transform:none}
  body.hasSb.sbOpen #sbBack{display:block; position:fixed; inset:0; background:rgba(15,35,66,.4); z-index:90}
  body.hasSb .mmIn{padding-top:14px}
}
@media (max-width:760px){
  #chrome{position:static}
  .topbar{height:auto; min-height:0; flex-wrap:wrap; padding:9px 12px 10px; gap:8px}
  .brandBlock{flex:1 1 auto; min-width:0; order:1}
  body.hasSb #sbBtn{order:0}
  .tbActs{order:2; margin-left:0; gap:0}
  .tbActs .refreshBtn.opt, .tbActs .blogBtn{display:none}
  .searchWrap{order:3; flex:1 1 100%; max-width:none; width:100%; margin:0}
  .searchInput{height:44px; font-size:16px; border-radius:12px; background-color:#f1f3f8}
  .searchItem{min-height:48px}
  .wrap{padding:12px 12px 70px}
  body.hasSb #mainMenuBar{top:0}
  .heroName{font-size:17px}
  .card{padding:13px 13px}
  .empty{padding:36px 12px 24px}
}
"""

ADMIN_CSS = TOKENS + r"""
/* ═══ v166 스킨 — 관리자 콘솔 / 회원 메뉴 화면 ═══ */
body{font-family:'Pretendard',system-ui,-apple-system,'Malgun Gothic',sans-serif;font-size:13px;background:var(--bg);color:var(--text);line-height:1.5;-webkit-font-smoothing:antialiased}
header{background:#fff;color:var(--navy);padding:0 18px;height:52px;border-bottom:1px solid var(--border);gap:8px;flex-wrap:nowrap}
header b{font-size:14.5px;font-weight:800;letter-spacing:-.02em}
header #ver{opacity:1;color:var(--muted);font-weight:600;font-size:11px}
header a.home{color:var(--text2);font-weight:600;margin-right:2px;padding:6px 10px;border-radius:8px}
header a.home:hover{background:#f1f3f8;color:var(--navy)}
header button{background:#fff;color:var(--text2);border:1px solid var(--border);border-radius:8px;padding:6px 11px;font-weight:600}
header button:hover{border-color:var(--ac);color:var(--ac)}
header button.red{background:#fff;color:#b4232f;border-color:#f1c9cd}
header button.red:hover{background:#fdf1f2;border-color:#e5384d;color:#b4232f}
#saveStat{color:var(--good)}
.w{max-width:1160px;padding:16px 20px 60px}

/* 왼쪽 사이드바 (관리자 콘솔 단독 화면) */
body:not(.emb):not(.mem) .w{display:grid;grid-template-columns:200px minmax(0,1fr);gap:0 22px;max-width:1320px;align-items:start}
body:not(.emb):not(.mem) nav{display:block;position:sticky;top:68px;margin:0;max-height:calc(100vh - 84px);overflow-y:auto;padding:2px 0 20px;grid-column:1}
body:not(.emb):not(.mem) #pane{grid-column:2;min-width:0}
body:not(.emb):not(.mem) #intro{grid-column:1/-1}
.ng{display:block;background:transparent;border:0;border-radius:0;padding:0;margin:0 0 6px}
.ngl{display:block;margin:10px 10px 4px;font-size:11px;font-weight:700;color:#8a93a6;letter-spacing:.06em}
.ng.dd{padding:0}
.ngb{display:flex;width:100%;justify-content:space-between;align-items:center;background:transparent!important;border:0!important;border-radius:6px;padding:9px 10px 4px;font-size:11px;font-weight:700;color:#8a93a6!important;letter-spacing:.06em;cursor:default}
.ngb em{display:none}
.ngb.on{color:var(--navy)!important}
.ng.open .ngb,.ng.open .ngb.on{background:transparent!important}
.ngd{display:flex!important;position:static;min-width:0;padding:0;border:0;box-shadow:none;background:transparent;border-radius:0;gap:1px;flex-direction:column}
nav button,.ngd button{display:block;width:100%;text-align:left;border:0;background:transparent;border-radius:8px;padding:7px 10px;font-size:13px;font-weight:500;color:var(--text2);cursor:pointer;position:relative;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
nav button:hover,.ngd button:hover{background:#f0f2f8;color:var(--navy)}
nav button.on,.ngd button.on{background:var(--acs);color:var(--ac2);font-weight:700}
nav button.on:not(.ngb):before,.ngd button.on:before{content:"";position:absolute;left:0;top:7px;bottom:7px;width:3px;border-radius:0 3px 3px 0;background:var(--ac)}
/* 메인 화면 안에 들어간 관리자(embed=full)·회원 화면: 얇은 탭 줄 */
body.emb:not(.one) nav{display:flex;gap:2px 4px;flex-wrap:wrap;margin:0 0 12px;border-bottom:1px solid var(--border);padding-bottom:6px}
body.emb:not(.one) .ng{display:flex;align-items:center;gap:2px;margin:0}
body.emb:not(.one) .ngl,body.emb:not(.one) .ngb{display:none}
body.emb:not(.one) .ngd{flex-direction:row;flex-wrap:wrap}
body.emb:not(.one) nav button,body.emb:not(.one) .ngd button{width:auto;padding:6px 11px;font-size:12.5px}
body.emb:not(.one) nav button.on:before,body.emb:not(.one) .ngd button.on:before{display:none}
body.emb .w{padding:12px 16px 40px;max-width:none}
body.mem .w{max-width:1100px}

/* 카드·표·버튼 */
.c{background:#fff;border:1px solid var(--border);border-radius:var(--radius);padding:10px 12px;margin:8px 0}
.h{background:#fffaf0;border-color:#f0d9a4}
.grid{grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:8px}
.k{background:#fff;border:1px solid var(--border);border-radius:10px;padding:11px 13px}
.k small{font-size:11px;color:var(--muted);font-weight:600}
.k b{font-size:19px;font-weight:800;letter-spacing:-.02em;color:var(--navy)}
table{font-size:12.5px;border:1px solid var(--border);border-radius:10px;background:#fff;border-collapse:separate;border-spacing:0}
td,th{padding:8px 10px;border-bottom:1px solid var(--line2)}
th{background:#f7f8fb;color:var(--text2);font-weight:700;font-size:11.5px}
tr:last-child td{border-bottom:0}
.note{color:var(--muted)}
.bt{background:var(--navy);border-radius:8px;padding:7px 12px;font-size:12.5px;font-weight:600}
.bt:hover{background:var(--navy2)}
.bt2{border:1px solid var(--border);background:#fff;color:var(--text);border-radius:8px;padding:6px 11px;font-size:12.5px;font-weight:600}
.bt2:hover{border-color:var(--ac);color:var(--ac)}
.bt3{border:1px solid var(--border);background:#f7f8fb;border-radius:6px;padding:3px 8px;font-size:11.5px}
.del{border-radius:8px;padding:6px 12px;font-size:12.5px}
.bar input,.bar select,textarea,input[type=text],input[type=number],input[type=password],input[type=date],select{border:1px solid var(--border);border-radius:8px;background:#fff;color:var(--text);font-family:inherit}
.bar input,.bar select{padding:6px 9px;font-size:12.5px}
input:focus,select:focus,textarea:focus{outline:none;border-color:var(--ac);box-shadow:0 0 0 3px rgba(36,87,214,.12)}
.cfBox{border-radius:14px}
.cfH{background:var(--navy);font-size:15px;padding:13px 18px}
.cfF button.go{background:var(--ac);border-color:var(--ac)}
#toast{border-radius:10px;font-size:12.5px}
#toast.ok{border-radius:999px}
.lockBar{border-radius:8px;padding:8px 11px;font-size:12.5px}
#mbar{background:#fff;color:var(--navy);border-bottom:1px solid var(--border);padding:10px 18px}
#mbar b{font-size:14px;font-weight:800}
#mbar a{color:var(--text2);font-weight:600;padding:4px 8px;border-radius:7px}
#mbar a:hover{background:#f1f3f8;color:var(--navy)}
#mbar .pv{background:#fdf0cf;color:#7a5a12}

/* 메뉴 모듈들의 큰 그라데이션 머리글 → 차분한 단색 */
.dpH,.dyH,.nwH{background:var(--navy)!important;border-radius:12px!important;box-shadow:none!important;padding:14px 18px!important}
.dlH{background:#8f1d1d!important;border-radius:12px!important;padding:12px 16px!important}
.dpH:before,.dpH:after,.dyH:before,.dyH:after{display:none!important}

/* 회원 메뉴 화면 머리글 */
#intro{margin:0 0 10px}
.itCard{border-radius:var(--radius);padding:12px 14px}
.itTop b{font-size:15.5px;letter-spacing:-.02em}
.itBadge{background:var(--acs);color:var(--ac2);font-size:11.5px}
.chip{font-size:11.5px;padding:3px 9px}
.itAct a{border-radius:8px;padding:6px 12px;font-size:12.5px;font-weight:600}
.itAct a.go{background:var(--ac);border-color:var(--ac)}

@media (max-width:860px){
  body:not(.emb):not(.mem) .w{display:block}
  body:not(.emb):not(.mem) nav{position:static;max-height:none;display:flex;flex-wrap:wrap;gap:2px 4px;margin-bottom:12px;border-bottom:1px solid var(--border);padding-bottom:8px;overflow:visible}
  body:not(.emb):not(.mem) .ng{display:flex;flex-wrap:wrap;gap:2px;margin:0}
  body:not(.emb):not(.mem) .ngl,body:not(.emb):not(.mem) .ngb{display:none}
  body:not(.emb):not(.mem) .ngd{flex-direction:row;flex-wrap:wrap}
  body:not(.emb):not(.mem) nav button,body:not(.emb):not(.mem) .ngd button{width:auto;padding:6px 11px;font-size:12.5px;border:1px solid var(--border);border-radius:999px;background:#fff}
  body:not(.emb):not(.mem) nav button.on,body:not(.emb):not(.mem) .ngd button.on{background:var(--navy);color:#fff;border-color:var(--navy)}
  body:not(.emb):not(.mem) nav button.on:before{display:none}
  header{padding:8px 12px;height:auto;flex-wrap:wrap;row-gap:6px}
  header b{flex:1 1 100%}
  body:not(.emb):not(.mem) nav{flex-wrap:nowrap;overflow-x:auto;-webkit-overflow-scrolling:touch;scrollbar-width:none}
  body:not(.emb):not(.mem) .ng,body:not(.emb):not(.mem) .ngd{flex-wrap:nowrap}
  body:not(.emb):not(.mem) nav button,body:not(.emb):not(.mem) .ngd button{flex:0 0 auto}
  #mbar{padding:9px 12px;gap:2px 4px}
  #mbar b{flex:1 1 100%;font-size:14px}
  .w{padding:12px 12px 48px}
}
"""

SUB_CSS = TOKENS + r"""
/* ═══ v166 스킨 — 도움말·방침 등 단순 페이지 ═══ */
body{background:var(--bg);color:var(--text);font-size:14px}
.topbar{background:#fff!important;color:var(--navy);box-shadow:none!important;border-bottom:1px solid var(--border);padding:0 18px!important;min-height:52px;display:flex;align-items:center}
.topbar .brand{color:var(--navy)!important;font-size:15px}
.topbar .brand span{color:var(--ac)!important}
.topbar .verTag{color:var(--muted)!important;opacity:1!important}
.topbar a.back{color:var(--text2)!important;background:#f1f3f8!important;border-radius:8px;padding:6px 12px}
.topbar a.back:hover{background:#e7eaf2!important;color:var(--navy)!important}
"""
