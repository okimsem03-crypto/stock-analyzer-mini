# -*- coding: utf-8 -*-
"""
📈 종목분석 미니 (공개판) — v122
────────────────────────────────────────────────────────────────
FinanceDataReader + 네이버 모바일 증권 API/FnGuide 공개 페이지만 사용합니다.
KRX 로그인, DART API 키, 유료 AI API 키가 전혀 필요 없습니다.

AI 해설은 "수동 모드"입니다 — 이 프로그램은 분석 프롬프트를 만들어 드릴
뿐, AI 호출은 직접 하지 않습니다. 만들어진 프롬프트를 복사해서 평소 쓰시는
AI 챗봇(ChatGPT·Claude·Gemini 등)에 붙여넣고, 돌아온 답변을 다시 이 프로그램에
붙여넣으면 보기 좋게 정리해서 보여줍니다.

💡 v107: 2026-09-11 네이버 증권 PC 개편(Next.js 리뉴얼)으로 이전 버전이 의존하던
finance.naver.com 페이지가 무력화되어, 개편과 무관한 네이버 모바일 증권 API로
데이터 소스를 전면 교체했습니다. 이 과정에서 이전엔 없던 동일업종 PEER 비교·
애널리스트 컨센서스(목표주가) 기능이 새로 추가되었고, 상장폐지 위험 감지도
더 안정적인 방식(거래상태 필드 + 시가총액 기준)으로 재설계되었습니다.

💡 v108: 세 가지 개선.
  ① 종합점수가 표시되지 않는 문제 수정 — 원인은 차트 라이브러리(ApexCharts, CDN
     로드)가 실패하면 그 예외가 화면 전체 렌더링을 중단시켜 이미 계산된 점수까지
     화면에 안 드러나던 것. 결과 화면을 먼저 연 뒤 렌더링하고, 차트 실패는
     차트 영역에서만 안내 메시지로 그치도록 격리했다.
  ② 상단 기업개요를 "네이버 우선 → 실패 시 AI 분석 결과에서 추출" 순서로 재구성.
     네이버 레거시 API로 실제 개요 문단을 먼저 시도하고, 실패하면 최근 증권사
     리포트 제목을 보여주며, 그래도 없으면 AI 분석(수동 붙여넣기) 결과의
     "[1. 기업 소개]" 섹션을 자동으로 추출해 상단 카드에 채운다.
  ③ GitHub 릴리스 기반 자동 업데이트 — 프로그램 시작 시 최신 버전을 확인해
     새 버전이 있으면 사용자 확인 없이 곧바로 내려받아 교체·재시작한다
     (Windows exe 전용, 아래 GITHUB_OWNER/GITHUB_REPO 설정 필요).

🐛 v109: v108에서 만든 자동 업데이트의 숨은 결함 수정 — 버전을 실행 파일명에서
읽던 기존 방식은, 자동 업데이트가 exe 파일을 "같은 파일명으로" 교체하기 때문에
(바탕화면 바로가기가 안 깨지도록) 한 번 업데이트하고 나면 그 뒤로는 버전이 영원히
그대로 보이는 문제가 있었다. 이제 exe로 빌드된 뒤에는 파일명이 아니라 코드에
하드코딩된 APP_VERSION_HARDCODED 값만 사용하므로, 여러 번 연속으로 자동
업데이트해도 매번 정확한 버전을 인식한다(스크립트로 직접 실행할 때는 기존처럼
파일명 기반 감지를 유지 — 개발 편의성 때문).

🐛 v110: "기업개요가 디자인 없이 이상한 텍스트 나열로 보인다" 신고 대응 — v108에서
"네이버 우선" 1순위로 추가했던 레거시 엔드포인트(getOverallInfo.nhn)를 실제로
써보니 회사 소개 문단이 아니라 전일가·시가·고가·거래량·시총·PER·EPS·PBR 같은
미니 시세 위젯 데이터를 그대로 텍스트로 나열해서 내려주는 것으로 확인되어(신고
주신 스크린샷으로 실측 확인) 완전히 제거했다. 이미 basic/integration API로 얻고
있는 수치를 형태만 다르게 중복 표시하는 것이었을 뿐, 기업 소개가 아니었다.
기업개요는 이제 증권사 리포트 제목 → (그것도 없으면) AI 분석 결과에서 자동 추출,
두 단계로만 채워진다.

💡 v111: "종합점수가 0점으로 나온다"(알테오젠 테스트) 신고 조사 결과 — 버그가
아니라 종합점수가 뉴스·펀더멘털을 전혀 반영하지 않는 순수 기술적 점수(추세·거래량·
52주위치·RSI)이기 때문이었다. 실제로 당시 알테오젠은 52주 최고가(569,000원)
대비 큰 폭 하락해 52주 최저가 부근에 머물던 시기였다 — 뉴스가 아무리 좋아도
이 점수엔 반영되지 않는다. 오해를 막기 위해 점수 카드 밑에 "기술적 지표만
반영" 안내를 상시 표시하고, 점수가 극단적일 때(0~20점 또는 80~100점)는 "52주
최저가 근접", "RSI 과매도"처럼 그 이유를 칩으로 함께 보여준다.

🐛 v112: "그래도 왜 아직 0점인지" 재문의(스크린샷) 대응 — v111에서 만든 이유 칩
자체에 버그가 있었다. "52주 최저가 근접" 칩은 위치 15% 미만일 때만 떴는데, 실제
점수 계산(tech_score)은 35% 미만이면 이미 감점하고 있어 — 알테오젠처럼 52주
위치가 15~35% 사이인 경우 점수엔 감점이 반영되면서도 그 이유를 알려주는 칩은
안 뜨는 불일치가 있었다. RSI·이평·거래량 칩은 원래 점수 계산과 같은 기준이라
문제없었고, 52주 위치 칩만 점수 계산과 같은 기준(35%)으로 맞추고 문구도 "52주
낮은 위치"로 조정했다(15%보다 완만한 구간까지 포함하므로 "최저가 근접"은 과함).

💡 v113: 사용자 요청에 따른 4가지 개선.
  ① 종합점수(및 관련 점수 카드·이유 칩) 완전 제거 — 기술적 지표만 반영하는 단일
     숫자가 "이 종목의 최종 평가"처럼 오해될 소지가 있다는 지적에 따라, quick_score/
     score_reasons 계산과 화면 표시를 모두 없앴다. 이제 각 지표는 아래 "기술적 지표"
     그리드에 개별적으로만 표시되며, 하나의 점수로 뭉뚱그리지 않는다.
  ② /help 도움말 페이지 신설 — 화면에 쓰인 증권 용어(RSI·이동평균 배열·거래량 배수·
     52주 위치·이격도·매물대 POC/VAL/VAH·일목균형표 구름·PER/PBR·배당수익률·
     컨센서스·상장폐지 위험 등)를 초보자 눈높이로 설명한다. 앱 버전(APP_VERSION_
     HARDCODED)과 도움말 최신화 시점(HELP_CONTENT_ASOF)이 어긋나면 도움말 상단에
     자동으로 "최신 내용과 다를 수 있음" 경고가 뜨도록 만들어, 향후 화면이 바뀌는데
     도움말 갱신을 깜빡하는 사고를 방지한다(위 HELP_CONTENT_ASOF 주석 참고).
  ③ 주가 차트에 일목균형표 구름(선행스팬A/B)·전환선·기준선과 매물대 POC/VAL/VAH
     지지·저항선을 함께 표시 — 기존엔 매물대 수치가 텍스트로만 안내되고 구름은
     아예 없었는데, 이제 차트 위에서 시각적으로 바로 확인할 수 있다(60거래일 이상
     보이도록 표시 구간 확대, 구름은 정의상 26일 앞으로 투영되므로 미래 영업일도
     함께 계산).
  ④ "기술적 지표" 카드 하단에 각 지표(RSI·이동평균 배열·거래량 배수·52주 위치·
     20일선 이격도·PER·PBR·배당수익률)의 의미를 짧게 풀어 설명하는 용어 해설
     영역을 추가 — 도움말 페이지로 가지 않고도 화면에서 바로 확인 가능.

🚀 v114: 웹 배포(서버 호스팅) 지원 추가 — 화면·기능 변경은 없고, 배포 방식만 넓혔다.
  ① PORT 환경변수 감지 — Render/Railway 등 대부분의 PaaS는 이 프로그램이 어떤 포트로
     떠야 하는지 PORT 환경변수로 알려준다. 이 값이 있으면 "웹 배포 모드"로 판단해
     0.0.0.0:$PORT 로 바인딩하고, GitHub 자동 업데이트 확인과 pywebview 창 띄우기(둘 다
     데스크톱 exe 전용 개념)를 건너뛴다. 없으면(평소 PC 실행) 기존과 완전히 동일하게
     127.0.0.1의 빈 포트를 찾아 창 앱(또는 기본 브라우저)으로 띄운다.
  ② DB 초기화(init_db)·종목 캐시 구축 스레드 시작을 main() 안에서 모듈 최상위로 이동 —
     gunicorn 같은 운영용 WSGI 서버는 "python 파일.py"처럼 main()을 호출하는 대신, 이
     모듈을 import한 뒤 그 안의 app 객체를 곧바로 사용한다. main() 안에만 있던 초기화
     코드는 그 경우 절대 실행되지 않으므로(=DB 테이블이 없어서 첫 요청부터 에러), 반드시
     "이 파일이 로드되는 순간" 실행되도록 옮겼다. 직접 실행(python 파일.py)할 때도 동작은
     이전과 동일 — 모듈이 어차피 import되는 순간 한 번 실행되고, main()은 그 뒤에 호출된다.
  ③ requirements.txt / Procfile 신설, 배포 가이드 문서 별도 제공(Render.com 기준).

💡 v115: 슬로건("모르면 물어보고, 알면 투자하세요") 추가 — 화면 상단 로고 옆과 첫
화면 안내문에 표시된다. 코드 여러 곳에 문구를 흩어놓지 않고 APP_SLOGAN 상수 하나로만
관리하도록 만들어, 나중에 더 나은 문구가 떠오르면 그 한 줄만 바꾸면 화면 전체(상단
태그·첫 화면 안내문)에 바로 반영되게 했다.

🚀 v116: [로드맵 0단계] "AI로 분석" 버튼을 눌러도 새 탭이 한참 뒤에 열리는 문제 해결.
원인은 그 버튼(copyAndOpenAI)이 `/api/ai-prompt/<ticker>` 응답을 다 받은 뒤에야 새 탭을
열었는데, 그 엔드포인트가 `/api/analyze`에서 이미 받아온 가격·기업개요·재무 데이터를
처음부터 네이버에서 다시 긁어오고 있었던 것 — 종목 하나를 볼 때 네이버 스크래핑이
사실상 두 번 일어나는 구조였다.
  ① (체감 지연 제거) 새 탭을 fetch 응답을 기다리지 않고 클릭 즉시 연다. 프롬프트 복사는
     응답이 오는 대로 백그라운드에서 처리하고 토스트로 완료를 안내한다.
  ② (중복 호출 제거) 클라이언트가 이미 가진 분석 결과(CUR)를 `/api/ai-prompt`에 함께
     실어 보내면(POST), 서버는 네이버 재조회 없이 그 데이터로만 프롬프트를 만든다.
     기존 방식(GET, 서버가 직접 재조회)은 그 데이터가 없을 때를 위한 폴백으로 남겨뒀다.

🚀 v117: [로드맵 1단계] 영구 저장소 도입 + 익명 검색 기록 — "커뮤니티로 성장하려면
먼저 누가 무엇을 봤는지 쌓여야 한다"는 로드맵 1단계 대응.
  ① 검색 기록 저장소 신설(search_history) — 로그인 없이, 첫 방문 시 서버가 쿠키로
     익명 uid(무작위 문자열, 개인식별정보 아님)를 심어 요청마다 함께 받는다. 종목을
     분석할 때마다 (uid, 종목코드, 종목명, 시장) 한 줄을 저장한다.
  ② DATABASE_URL 환경변수(Neon.tech·Supabase 등 외부 Postgres 무료 티어 권장)가
     설정되어 있으면 그쪽에 영구 저장 — Render 무료 웹서비스는 재배포·재시작마다 로컬
     디스크가 초기화되므로, 검색 기록처럼 사라지면 안 되는 데이터는 반드시 외부 DB에
     둬야 한다. DATABASE_URL이 없으면(로컬 PC 실행 등) 기존 SQLite 캐시 파일에 저장해
     최소한 지금 세션에서는 정상 동작한다(이 경우 Render에 그대로 올리면 재배포 시
     기록이 사라지니, 웹 배포에서는 DATABASE_URL 설정을 권장 — 웹배포_가이드.md 참고).
  ③ 화면에 "🕘 최근 본 종목" 칩 목록 추가(첫 화면) — 같은 브라우저면 새로고침해도,
     나중에 다시 방문해도 남아있다. 클릭하면 바로 그 종목을 다시 분석한다.
  ④ 이 저장소가 기존 종목명 캐시(mini_tickers.db)와 별개 테이블이라, 캐시가 비워져도
     검색 기록에는 영향이 없다(반대도 마찬가지).

🚀 v118: [로드맵 '초기 보급'] 첫 방문자 확보용 기능 5가지.
  ① 💬 카카오톡 오픈채팅 버튼 — KAKAO_OPENCHAT_URL 한 줄만 채우면 topbar에 노출된다.
     비워두면 버튼 자체가 숨겨지므로, 방을 만들기 전에 배포해도 안전하다.
  ② 🔗 공유(링크) + 🖼️ 이미지 저장 — 공유 링크는 "?t=종목코드" 형식이라 받은 사람이
     열면 같은 종목 결과가 바로 뜬다. 모바일·카카오톡 인앱에선 기기 공유 시트를, PC에선
     클립보드 복사를 쓴다. 이미지 저장은 html2canvas를 버튼을 누를 때만 불러와(평소
     로딩 속도 영향 없음) 결과 카드를 PNG로 내려받는다.
  ③ 🎬 데모 버튼 — 첫 화면에서 검색 없이 DEMO_TICKER(기본 삼성전자) 결과를 바로 체험.
  ④ 👥 누적 분석 건수 배지 — search_history를 그대로 집계(별도 테이블 없음). 0건이면 숨김.
  ⑤ 📝 블로그 내보내기 — AI 프롬프트와 달리 사람이 그대로 붙여넣는 완성된 글을 AI 호출 없이
     즉시 만든다. 사이트 링크(?t=)·오픈채팅 링크가 글 끝에 자동으로 붙는다.
  ※ /api/ai-prompt와 새 /api/blog-export는 공용 헬퍼(_resolve_analysis_source)를 함께
     써서, v116에서 고친 "매번 네이버 재조회" 문제가 새 기능에서 되풀이되지 않게 했다.
  ※ 최종 점검에서 함께 고친 것:
     - PUBLIC_SITE_URL(기본 https://chostock.kr) 추가 — 데스크톱에서 공유·블로그 링크가
       남의 PC에선 열리지 않는 127.0.0.1 주소로 만들어지던 문제 해결. 공유 이미지 하단에도 표기.
     - DB가 잠깐 안 붙어도 서버 부팅이 멈추지 않게 함(기록 기능만 쉬고, 다음 요청 때 재시도).
     - "최근 본 종목"이 같은 초에 본 종목끼리 순서가 뒤섞이던 문제 수정(저장 순서 id 기준 정렬).
     - 최근 본 종목 칩 HTML 이스케이프, anon_uid 쿠키 HttpOnly(+웹에선 Secure), POST 5MB 상한.
     - 창 앱(pywebview)에서도 이미지 저장이 되도록 다운로드 허용, 공유 이미지는 420px 카드로.
     - /healthz 헬스체크 주소 추가, 도움말에 ⑦ 공유·블로그·최근 본 종목 섹션 추가.

🚀 v119: 사용자 피드백 6가지 반영.
  ① ⚡ 분석 속도 — 주가·네이버 기본정보·네이버 종합정보·FnGuide를 차례로 부르던 것을 동시에
     불러 첫 분석 5.2초 → 약 1.8초(실측, 삼성전자). 종목별 결과를 장중 2분·장외 30분 캐시해
     다시 보면 즉시(0.00초), 같은 종목 동시 요청은 한 번만 조회, 데모·인기 종목은 미리 불러둔다.
     응답 gzip 압축(25KB → 8KB), 분석 중 단계별 로딩 화면, 브라우저 쪽 2분 캐시.
  ② 🔗 링크 공유 고장 수정 — (a) 윈도우 크롬·엣지에도 navigator.share가 있어 PC에서 윈도우
     공유창이 떴음 → 휴대폰에서만 공유창, PC는 복사. (b) 복사 실패도 "복사됨"으로 표시하던
     _copyText 수정. (c) 도메인 연결 전 chostock.kr로 링크가 만들어져 열리지 않았음 → 방문자가
     실제로 들어온 주소로 생성. 링크를 화면의 칸에도 보여줘 직접 복사할 수 있게 함.
  ③ 📄 전체 리포트 PDF — 결과 화면(+붙여넣은 AI 분석)을 A4 PDF로 저장. 모든 페이지 위·아래에
     chostock.kr·제작자 블로그 배너(누르면 이동), 카드가 페이지 경계에서 잘리지 않게 분할.
  ④ 💰 구글 애드센스 자리 사전 구성 — ADSENSE_CLIENT/ADSENSE_SLOTS 상수, 자리 4곳(첫 화면
     하단·결과 상단·중간·하단), ?adpreview=1 미리보기, /ads.txt 자동 생성, /privacy 개인정보처리방침.
  ⑤ 🤖 AI 버튼 — 분석 직후 프롬프트를 미리 만들어 두어, 버튼을 누르는 순간 이미 복사되어 있다.
     안내창(복사·붙여넣기 순서)을 띄우고, [열기]는 진짜 링크라 팝업 차단에 걸리지 않는다.
     ("다음부터 안내 없이 바로 열기" 선택 가능)
  ⑥ 🤖 AI 답변 자동 붙여넣기 — AI 화면에서 답변을 복사하고 돌아오면 클립보드를 읽어 AI 칸에
     바로 넣고 정리. 브라우저가 막으면 [📥 복사한 답변 붙여넣기] 버튼·Ctrl+V 안내.
  ※ REDIRECT_TO_PUBLIC_SITE(도메인 연결 후 onrender.com → chostock.kr 자동 이동), CREATOR_BLOG_URL 상수 추가.

🐛 v120: "평소보다 오래 걸리다가 결국 '주가 데이터를 가져오지 못했습니다'로 실패" 대응.
  원인: 주가를 가져오는 FinanceDataReader에는 자체 대기시간이 없어, 네이버가 서버(Render)의
  요청에 늦게 답하면 v119가 정한 25초 제한에 걸려 실패했다(v119는 요청을 동시에 여러 개
  보내고 서버 시작 직후 미리 불러오기까지 해서 네이버 쪽 지연이 생기기 쉬웠다).
  ① 주가를 서로 다른 네이버 서버 세 곳에서 차례로 시도(api.stock.naver.com → FDR → fchart),
     각각 8~12초 제한. 모든 네이버 요청에 일시 오류 자동 재시도(최대 2회).
  ② 그래도 실패하면 최근 3일 안에 성공했던 결과를 기준 시각과 함께 보여준다(빈 화면 방지).
  ③ 미리 불러오기는 서버 시작 20초 뒤부터, 종목 사이 3초 간격, 대상 3개로 축소.
  ④ 실패하면 이유와 [다시 시도] 버튼을 화면에 표시. /api/diag 진단 페이지 추가(각 경로 성공 여부·시간).

🚀 v121: 사용자 요청 4가지.
  ① ↺ 초기화 버튼(상단) — 검색·결과·AI 칸을 비우고 첫 화면으로. 최근 본 종목 [기록 지우기].
  ② 📑 재무 정보 — 네이버 모바일 증권 API의 연간(3년+추정)·분기(5개+추정) 매출·영업이익·순이익·
     이익률·ROE·부채비율·당좌비율·유보율·EPS·BPS·배당·PER·PBR을 표·그래프로(12시간 캐시).
     AI 프롬프트에 재무 추이 표와 [3. 실적·재무 분석] 섹션 추가, 블로그 글에 실적 한 줄 추가.
  ③ 📰 최근 2주 뉴스 — 14일 이내 기사만(같은 사건 묶음은 대표 1건 + 관련 건수), 프롬프트에 제목 포함
     ([4. 최근 뉴스·이슈 점검] 섹션, 제목 밖 내용 추측 금지 지시).
  ④ 💡 매력도 체크 — 사고 싶어요/지켜볼래요/아직은 투표(한 브라우저 종목당 한 표, 최근 30일 집계),
     첫 화면 "이번 주 매수 관심 TOP 5". stock_votes 테이블(SQLite·Postgres 공통 SQL).

🌐 v122: "네이버에서 데이터를 못 가져오는 경우가 많다" — 야후 파이낸스를 네이버와 무관한 예비 시세
  소스로 추가(코스피 .KS / 코스닥 .KQ, 영문 코드 포함). 순서: 네이버 API → 야후 → FDR → fchart.
  주가 소스끼리는 재시도 없이 바로 다음으로 넘어가고(연결 3초·응답 6초 제한), 5분 안에 2번 연결 오류가
  난 소스는 3분 동안 뒤로 미룬다. 네이버가 불안정한 동안에는 네이버 전용 정보(기업정보·재무·뉴스)를
  건너뛰어 야후 시세로 빠르게 결과를 보여주고, 화면에 시세 출처와 "일부 정보 빠짐"을 안내한다.
  /api/diag에 소스별 상태 표시.

실행(로컬/데스크톱):  python stock_analyzer_mini.py
실행(웹 서버, 예: Render):  gunicorn stock_analyzer_mini:app --bind 0.0.0.0:$PORT
필요:  pip install flask finance-datareader pandas numpy requests beautifulsoup4
       (pip install pywebview  → 있으면 창 앱으로, 없으면 기본 브라우저로 실행됩니다)
       (웹 배포 시엔 pip install gunicorn 도 필요 — requirements.txt에 포함됨)
       (영구 검색 기록을 쓰려면 pip install psycopg2-binary + DATABASE_URL 환경변수
        설정 — 둘 다 없어도 프로그램은 정상 실행되고, SQLite로 자동 대체된다)

exe 빌드(PyInstaller):
  pip install pyinstaller pywebview
  pyinstaller --onefile --noconsole --name "종목분석미니_v122" stock_analyzer_mini.py
  (--noconsole은 창 앱 모드일 때만 권장 — 콘솔 로그로 문제를 확인하려면 빼고 빌드하세요)
  빌드된 exe와 같은 폴더에 mini_tickers.db 캐시 파일이 자동 생성됩니다.

GitHub 자동 업데이트를 쓰려면(선택, exe 전용 — 웹 배포 모드에선 자동으로 건너뜀):
  1) GitHub 저장소를 만들고, 아래 GITHUB_OWNER/GITHUB_REPO를 본인 것으로 바꾸세요.
  2) 새 버전을 낼 때마다 코드 상단의 APP_VERSION_HARDCODED 값을 올리세요(예: "v112")
     — exe로 빌드된 뒤에는 파일명이 아니라 이 값으로만 버전을 판단합니다.
  3) "Releases"에 그 버전과 같은 태그(예: v112)를 달고, PyInstaller로 빌드한 exe
     파일을 GITHUB_ASSET_NAME과 정확히 같은 이름으로 첨부해 업로드하세요.
  4) 이후 사용자가 exe를 실행하면 시작 시 자동으로 새 버전을 확인·교체합니다.
"""

import os, sys, math, re, sqlite3, threading, socket, webbrowser, time, subprocess, uuid, gzip
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, Future
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
import requests
from flask import Flask, jsonify, request, render_template_string, g

# ── 선택적 의존성 ──────────────────────────────────────────────
try:
    import FinanceDataReader as fdr
    FDR_OK = True
except Exception:
    FDR_OK = False

try:
    from bs4 import BeautifulSoup
    BS4_OK = True
except Exception:
    BS4_OK = False

# 💡 [v117] 영구 검색 기록 저장(1단계)에 Postgres를 쓸 때만 필요 — 없어도(즉 로컬 PC에서
# 그냥 실행하거나, 웹 배포인데 아직 DATABASE_URL을 안 만들었을 때도) 프로그램은 정상
# 실행되고, 기존처럼 SQLite로 자동 대체된다(아래 "검색 기록 저장소" 섹션 참고).
try:
    import psycopg2
    PG_OK = True
except Exception:
    PG_OK = False

APP_VERSION_HARDCODED = "v122"  # ⚠️ 이 프로그램의 진짜 버전. 새 버전을 낼 때마다 반드시 이 값을
                                  # 올리세요 — GitHub 자동 업데이트의 버전 비교가 이 값을 기준으로
                                  # 동작합니다(아래 설명 참고).

# ⚠️⚠️⚠️ [v113] /help 도움말 페이지 최신화 규칙 — 반드시 지킬 것 ⚠️⚠️⚠️
# 화면에 새로운 용어·지표·기능이 추가되거나 기존 용어의 의미/계산 방식이 바뀔 때마다,
# 아래 HELP_HTML(증권용어 도움말 본문)도 함께 갱신하고 이 HELP_CONTENT_ASOF 값을
# 그때의 APP_VERSION_HARDCODED와 "같은 값"으로 올려야 한다. 두 값이 다르면(즉 도움말을
# 갱신하지 않고 앱 버전만 올리면) /help 페이지 상단에 "도움말이 최신 버전 내용과 다를 수
# 있습니다" 경고 배너가 자동으로 표시된다(아래 help_page() 라우트의 stale 판정 로직 참고).
# 이 자동 경고 덕분에, 도움말 갱신을 깜빡해도 사용자에게 잘못된 설명이 조용히 방치되는
# 대신 최소한 "오래됐을 수 있다"는 신호는 보이게 된다. 새 버전을 낼 때는:
#   1) 새로 생기거나 바뀐 화면 용어를 HELP_HTML 안의 해당 섹션(sec-trend/sec-chart/
#      sec-value/sec-peer/sec-risk/sec-ai)에 반영
#   2) HELP_CONTENT_ASOF = APP_VERSION_HARDCODED 와 같은 값으로 갱신
# 💡 v114는 배포 방식(웹 서버 지원)만 바꿨을 뿐 화면 용어·기능은 그대로이므로, 도움말
#    본문은 손대지 않고 이 값만 같이 올렸다(그래야 "오래됐을 수 있음" 배너가 잘못 뜨지 않음).
# 💡 v116~v118도 마찬가지 — AI 링크 속도 개선과 "최근 본 종목" 기록은 증권 용어가 아니라
#    도움말 본문을 바꿀 내용이 없으므로, 이 값만 같이 올렸다.
HELP_CONTENT_ASOF = "v122"

# 📣 슬로건 — 화면 상단(로고 옆)과 첫 화면 안내문에 그대로 표시된다.
# 더 좋은 문구가 떠오르면 이 한 줄만 바꾸면 된다(코드의 다른 곳은 전혀 손댈 필요 없음).
APP_SLOGAN = "모르면 물어보고, 알면 투자하세요"

# 💬 [v118] 카카오톡 오픈채팅 — "초기 보급" 1순위 항목(코드 한 줄). 아직 방을 안 만들었으면
# 빈 문자열로 두세요 — 빈 값이면 화면에 버튼 자체가 나타나지 않으니 그대로 배포해도 안전합니다.
# 방을 만든 뒤 이 한 줄만 채우면 topbar에 바로 버튼이 뜹니다.
KAKAO_OPENCHAT_URL = ""  # 예: "https://open.kakao.com/o/xxxxxxxx"

# 🎬 [v118] 데모 버튼이 첫 방문자에게 보여줄 종목 — 검색 없이 결과 화면을 바로 체험하게
# 해서 첫 방문 이탈을 줄이기 위한 용도(전환율 개선). 다른 종목으로 바꾸고 싶으면 이
# 두 줄만 수정하면 된다.
DEMO_TICKER = "005930"
DEMO_TICKER_NAME = "삼성전자"

# 🌐 [v118] 공개 사이트 주소 — 공유 링크·블로그 글 링크·공유 이미지 하단 표기에 쓰인다.
# 데스크톱(exe)으로 실행해도 링크가 내 PC 주소(127.0.0.1)가 아니라 이 주소로 만들어지고,
# onrender.com 주소로 들어온 사람에게도 대표 주소로 통일된다. 비우면 접속한 주소를 그대로 쓴다.
PUBLIC_SITE_URL = "https://chostock.kr"

# 🔁 [v119] chostock.kr 연결이 끝난 뒤 True로 바꾸면, onrender.com 주소로 들어온 방문자를
# chostock.kr로 자동으로 옮겨준다(검색엔진·공유 주소를 대표 주소 하나로 모음). 도메인이
# 아직 연결되지 않았을 때 켜면 사이트가 안 열리니, 연결 확인 후에만 켜세요.
REDIRECT_TO_PUBLIC_SITE = False

# ✍️ [v119] 제작자 블로그 — 상단 버튼과 PDF 리포트 위·아래 광고 배너에 쓰인다.
CREATOR_BLOG_URL = "https://blog.naver.com/okykr"

# 💰 [v119] 구글 애드센스 — 승인받은 뒤 아래 값만 채우면 광고가 붙는다(비어 있으면 광고 없음).
#   ADSENSE_CLIENT: 애드센스의 게시자 ID(예: "ca-pub-1234567890123456"). 이것만 채우면
#     "자동 광고"(구글이 알아서 위치 선정)가 켜지고, /ads.txt도 자동으로 만들어진다.
#   ADSENSE_SLOTS: 광고 단위를 직접 만들었다면 각 자리의 광고 단위 ID(숫자)를 넣는다.
#     비워둔 자리는 표시하지 않는다. 주소 뒤에 ?adpreview=1 을 붙여 열면 각 자리가
#     점선 상자로 보여 위치를 미리 확인할 수 있다.
ADSENSE_CLIENT = ""
ADSENSE_SLOTS = {
    "home_bottom": "",     # 첫 화면, 소개 카드 아래
    "result_top": "",      # 결과 화면, 투자 팁 배너 바로 아래(첫 화면 안쪽)
    "result_middle": "",   # 결과 화면, 차트·해설과 기업개요 사이
    "result_bottom": "",   # 결과 화면, AI 분석 카드 아래·면책 문구 위
}
ADSENSE_SLOT_HINTS = {
    "home_bottom": "첫 화면 · 반응형 디스플레이 광고 권장",
    "result_top": "결과 상단 · 반응형 디스플레이 광고 권장(버튼과 충분히 떨어뜨림)",
    "result_middle": "결과 중간 · 인피드/반응형 광고 권장",
    "result_bottom": "결과 하단 · 반응형 디스플레이 광고 권장",
}


def _detect_app_version():
    """💡 [v102] 스크립트로 직접 실행할 때(.py)는 파일명에서 'vNNN'을 추출해 보여준다
       (예: stock_analyzer_mini_v103.py → v103) — 여러 버전 파일을 나란히 두고 테스트할 때
       편하기 때문. 🐛 [v108] 단, exe로 빌드된 뒤에는 파일명을 신뢰하지 않는다: 자동
       업데이트가 실행 파일을 교체할 때 "기존과 같은 경로/파일명"으로 덮어쓰므로(바탕화면
       바로가기 등이 깨지지 않도록), exe의 파일명은 처음 빌드했을 때 이름으로 영원히
       고정된다 — 파일명으로 버전을 읽으면 업데이트해도 버전이 영원히 안 올라가는
       버그가 생긴다. 그래서 얼어붙은(frozen) 실행 파일일 때는 항상 위 하드코딩된
       APP_VERSION_HARDCODED를 그대로 쓴다(이 값은 새 버전을 빌드할 때 코드에서
       직접 올리는, 유일하게 신뢰할 수 있는 버전 정보)."""
    if getattr(sys, "frozen", False):
        return APP_VERSION_HARDCODED
    try:
        m = re.search(r"[_\-][vV](\d+)", os.path.basename(__file__))
        if m:
            return "v" + m.group(1)
    except Exception:
        pass
    return APP_VERSION_HARDCODED


APP_VERSION = _detect_app_version()
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                     "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"}

# 실행 파일/스크립트가 있는 폴더에 작은 캐시 DB(종목명 검색용)만 둔다.
_BASE_DIR = os.path.dirname(os.path.abspath(
    sys.argv[0] if getattr(sys, "frozen", False) else __file__))
DB_PATH = os.path.join(_BASE_DIR, "mini_tickers.db")

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 5 * 1024 * 1024  # [v118] POST 본문 상한 5MB(분석 결과 전송은 수십 KB)


# ══════════════════════════════════════════════════════════════
# 익명 uid 쿠키 (⚠️ v117: 로드맵 1단계) — 로그인 없이 "이 브라우저"를 구분하기 위한
# 무작위 문자열. 첫 요청에 쿠키가 없으면 여기서 하나 만들어 이번 요청 처리 중에도
# g.anon_uid로 바로 쓸 수 있게 하고, 응답에 쿠키로 심어 다음 방문부터 같은 값이 오게
# 한다. 실명·이메일 등과 연결되지 않으며, 오직 "같은 브라우저가 다시 왔는지"만 안다.
# ══════════════════════════════════════════════════════════════
@app.before_request
def _ensure_anon_uid():
    g.anon_uid = request.cookies.get("anon_uid") or uuid.uuid4().hex


@app.after_request
def _gzip_response(resp):
    """⚡ [v119] 화면(HTML)과 분석 결과(JSON)를 압축해 보낸다 — 휴대폰 등 느린 망에서 체감
       속도가 크게 좋아진다(분석 결과 약 25KB → 6KB). 이미 압축된 응답은 건드리지 않는다."""
    try:
        if (resp.direct_passthrough or not (200 <= resp.status_code < 300)
                or "gzip" not in request.headers.get("Accept-Encoding", "").lower()
                or resp.headers.get("Content-Encoding")):
            return resp
        mt = resp.mimetype or ""
        if not (mt.startswith("text/") or mt in ("application/json", "application/javascript")):
            return resp
        data = resp.get_data()
        if len(data) < 1024:
            return resp
        body = gzip.compress(data, compresslevel=5)
        resp.set_data(body)
        resp.headers["Content-Encoding"] = "gzip"
        resp.headers["Content-Length"] = str(len(body))
        resp.vary.add("Accept-Encoding")
    except Exception:
        pass
    return resp


@app.after_request
def _set_anon_uid_cookie(resp):
    if request.cookies.get("anon_uid") != g.get("anon_uid"):
        resp.set_cookie("anon_uid", g.anon_uid, max_age=60 * 60 * 24 * 365 * 2, samesite="Lax",
                        httponly=True,          # 자바스크립트가 읽을 필요 없음 → 탈취 위험 차단
                        secure=_WEB_MODE)       # 웹 배포(https)에서만 secure — 로컬 http에선 끔
    return resp


# ══════════════════════════════════════════════════════════════
# 🔄 [v108] GitHub 자동 업데이트
# ──────────────────────────────────────────────────────────────
# ⚠️ 배포 전 반드시 아래 3개 값을 본인의 실제 GitHub 저장소에 맞게 바꿔주세요.
# GITHUB_ASSET_NAME은 "고정값"입니다 — GitHub Release를 올릴 때마다 exe 파일을
# 반드시 이 이름 그대로 업로드해야 프로그램이 찾을 수 있습니다(버전마다 파일명이
# 바뀌면 자동 인식이 안 됩니다).
#
# 릴리스 태그(tag) 이름은 "v108", "v109"처럼 APP_VERSION과 같은 형식을 쓰세요
# (숫자만 비교하므로 "v108"이든 "1.0.8"이든 상관없지만, 통일하는 걸 권장합니다).
#
# 동작 방식: 프로그램 시작 시 GitHub의 "최신 릴리스"를 확인해, 태그의 버전이 현재
# 실행 중인 버전보다 높으면 "무조건"(사용자 확인 없이) 새 exe를 내려받아 자신을
# 교체하고 재시작합니다. Windows에서는 실행 중인 exe 파일 자체를 덮어쓸 수 없어서,
# 별도의 작은 배치 스크립트가 "이 프로그램이 완전히 종료되기를 기다렸다가 → 파일을
# 교체하고 → 다시 실행"하는 전형적인 자기 업데이트(self-update) 패턴을 사용합니다.
# 이 기능은 PyInstaller로 빌드된 Windows exe에서만 동작하며, python으로 직접 실행하는
# 스크립트 모드에서는(개발 중 테스트 등) 안전하게 건너뜁니다. 네트워크 문제 등으로
# 확인이나 다운로드에 실패해도 프로그램은 현재 버전으로 정상 실행됩니다(업데이트
# 실패가 프로그램 실행 자체를 막지 않습니다).
# ══════════════════════════════════════════════════════════════
GITHUB_OWNER = "your-github-username"        # ⚠️ 본인 GitHub 계정명으로 교체
GITHUB_REPO = "stock-analyzer-mini"          # ⚠️ 본인 저장소 이름으로 교체
GITHUB_ASSET_NAME = "stock_analyzer_mini.exe"  # 매 릴리스마다 이 이름 그대로 업로드
UPDATE_CHECK_TIMEOUT = 4     # 초 — 버전 확인 자체가 느리면 그냥 포기하고 정상 실행
UPDATE_DOWNLOAD_TIMEOUT = 30  # 초 — 다운로드 중 각 구간(청크)에 대한 대기시간(전체 제한 아님)


def _version_tuple(v):
    """'v108' → (108,), '1.2.3' → (1,2,3) 형태로 파싱해 버전을 비교 가능하게 만든다.
       숫자가 하나도 없으면 (0,)을 반환해 항상 '더 낮은 버전'으로 취급한다."""
    nums = re.findall(r"\d+", v or "")
    return tuple(int(n) for n in nums) if nums else (0,)


def check_github_update():
    """GitHub 최신 릴리스를 확인한다. 반환: (업데이트있음: bool, 새버전태그: str|None,
       exe 다운로드 URL: str|None). 저장소 미설정·네트워크 오류·릴리스 없음 등
       어떤 이유로든 실패하면 예외를 던지지 않고 (False, None, None)을 반환해,
       이 기능 때문에 프로그램이 실행 자체를 못 하는 일이 없게 한다."""
    if GITHUB_OWNER == "your-github-username" or GITHUB_REPO == "stock-analyzer-mini":
        # 아직 배포자가 저장소 정보를 설정하지 않은 상태 — 조용히 건너뛴다(에러 아님).
        return False, None, None
    try:
        url = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/releases/latest"
        r = requests.get(url, timeout=UPDATE_CHECK_TIMEOUT,
                          headers={"Accept": "application/vnd.github+json"})
        if r.status_code != 200:
            return False, None, None
        data = r.json()
        latest_tag = (data.get("tag_name") or "").strip()
        if not latest_tag or _version_tuple(latest_tag) <= _version_tuple(APP_VERSION):
            return False, None, None
        download_url = None
        for asset in (data.get("assets") or []):
            if asset.get("name") == GITHUB_ASSET_NAME:
                download_url = asset.get("browser_download_url")
                break
        if not download_url:
            print(f"[자동업데이트] 릴리스 {latest_tag}는 있지만 '{GITHUB_ASSET_NAME}' 파일을 찾지 못했습니다.")
            return False, None, None
        return True, latest_tag, download_url
    except Exception as e:
        print(f"[자동업데이트] 확인 실패(현재 버전으로 계속 실행): {e}")
        return False, None, None


def _perform_self_update(download_url, new_version, progress_cb=None):
    """새 exe를 내려받아 현재 실행 파일을 교체하는 배치 스크립트를 만들어 실행한 뒤
       현재 프로세스를 종료한다. 성공적으로 교체 절차가 "시작"되면 True(호출자는 즉시
       종료해야 함), 무엇이든 실패하면 False(호출자는 현재 버전으로 계속 실행)를 반환한다.
       Windows에서 PyInstaller로 빌드된 exe로 실행 중일 때만 동작한다."""
    if not getattr(sys, "frozen", False):
        print("[자동업데이트] 스크립트 실행 모드에서는 자동 교체를 지원하지 않습니다 — "
              "GitHub에서 최신 버전을 직접 받아주세요.")
        return False
    if os.name != "nt":
        print("[자동업데이트] 현재 Windows 전용 기능입니다 — GitHub에서 최신 버전을 직접 받아주세요.")
        return False

    tmp_path = None
    try:
        cur_exe = os.path.abspath(sys.argv[0])
        cur_dir = os.path.dirname(cur_exe)
        tmp_path = os.path.join(cur_dir, f"_update_{new_version}.tmp")

        with requests.get(download_url, stream=True, timeout=UPDATE_DOWNLOAD_TIMEOUT) as r:
            r.raise_for_status()
            total = int(r.headers.get("Content-Length", 0) or 0)
            done = 0
            with open(tmp_path, "wb") as f:
                for chunk in r.iter_content(chunk_size=262144):
                    if not chunk:
                        continue
                    f.write(chunk)
                    done += len(chunk)
                    if progress_cb:
                        try:
                            progress_cb(done, total)
                        except Exception:
                            pass

        # 다운로드가 중간에 끊겨 너무 작은 파일이 되면(정상 exe는 최소 수MB) 교체를 포기한다
        # — 손상된 파일로 기존 정상 실행 파일을 덮어써서 프로그램이 아예 안 켜지게 되는
        # 사고를 막기 위한 안전장치.
        if not os.path.exists(tmp_path) or os.path.getsize(tmp_path) < 1024 * 1024:
            print("[자동업데이트] 다운로드 파일이 비정상적으로 작아 교체를 취소합니다.")
            try:
                os.remove(tmp_path)
            except Exception:
                pass
            return False

        pid = os.getpid()
        bat_path = os.path.join(cur_dir, "_updater.bat")
        # tasklist로 "이 프로그램의 PID가 더는 실행 중이 아닐 때까지" 기다린 뒤 교체한다
        # — 고정된 대기시간(예: 2초) 대신 실제 종료를 확인하므로, 종료가 느린 PC에서도
        # "파일이 사용 중이라 교체 실패" 하는 경우를 줄인다.
        bat_content = (
            "@echo off\r\n"
            "chcp 65001 >nul\r\n"
            ":wait\r\n"
            f'tasklist /fi "PID eq {pid}" 2^>nul ^| find "{pid}" >nul\r\n'
            "if not errorlevel 1 (\r\n"
            "  timeout /t 1 /nobreak >nul\r\n"
            "  goto wait\r\n"
            ")\r\n"
            f'move /y "{tmp_path}" "{cur_exe}" >nul\r\n'
            f'start "" "{cur_exe}"\r\n'
            'del "%~f0"\r\n'
        )
        with open(bat_path, "w", encoding="utf-8") as f:
            f.write(bat_content)

        CREATE_NO_WINDOW = 0x08000000
        DETACHED_PROCESS = 0x00000008
        subprocess.Popen(
            ["cmd", "/c", bat_path],
            creationflags=CREATE_NO_WINDOW | DETACHED_PROCESS,
            close_fds=True,
        )
        return True
    except Exception as e:
        print(f"[자동업데이트] 업데이트 중 오류(현재 버전으로 계속 실행): {e}")
        if tmp_path:
            try:
                os.remove(tmp_path)
            except Exception:
                pass
        return False


def _show_update_splash(new_version):
    """업데이트 다운로드 진행률을 보여주는 아주 가벼운 안내창(Tkinter — 파이썬 표준
       라이브러리라 추가 설치가 필요 없다). --noconsole로 빌드된 exe는 콘솔 출력이
       화면에 안 보이므로, 이 창이 없으면 다운로드 중에 사용자가 "프로그램이 멈췄다"고
       오해하고 강제 종료해버릴 수 있다. 창을 못 띄워도(디스플레이 문제 등) 업데이트
       자체는 계속 진행되도록 예외를 조용히 삼킨다."""
    try:
        import tkinter as tk
        root = tk.Tk()
        root.title("종목분석 미니 - 업데이트")
        root.geometry("380x150")
        root.resizable(False, False)
        try:
            root.eval("tk::PlaceWindow . center")
        except Exception:
            pass
        tk.Label(root, text=f"🔄 새 버전({new_version})으로 업데이트하는 중입니다...",
                 font=("Malgun Gothic", 11, "bold"), pady=14).pack()
        pct_label = tk.Label(root, text="0%", font=("Malgun Gothic", 10))
        pct_label.pack()
        canvas = tk.Canvas(root, width=320, height=18, bg="#e5e7eb", highlightthickness=0)
        canvas.pack(pady=8)
        bar = canvas.create_rectangle(0, 0, 0, 18, fill="#2563eb", width=0)
        tk.Label(root, text="완료되면 자동으로 새 버전이 실행됩니다. 잠시만 기다려 주세요.",
                 font=("Malgun Gothic", 8), fg="#888888").pack()
        root.update()
        return {"root": root, "canvas": canvas, "bar": bar, "pct_label": pct_label}
    except Exception as e:
        print(f"[자동업데이트] 진행 안내창을 열지 못했습니다(다운로드는 계속 진행): {e}")
        return None


def _update_splash_progress(state, done, total):
    if not state:
        return
    try:
        pct = int(done / total * 100) if total else 0
        state["canvas"].coords(state["bar"], 0, 0, 320 * pct / 100, 18)
        state["pct_label"].config(text=f"{pct}%" + ("" if total else f" ({done//1024}KB)"))
        state["root"].update()
    except Exception:
        pass


def run_auto_update_check():
    """💡 [v108] 프로그램 시작 시 1회 호출 — GitHub에 현재보다 새 버전이 있으면
       사용자 확인 없이("무조건") 곧바로 업데이트를 진행한다. 이 함수는 항상 안전하게
       반환한다: 업데이트를 시작했다면(=현재 프로세스가 곧 종료될 것이므로) True를
       반환하고, 그 외의 모든 경우(업데이트 없음·확인 실패·비-Windows·스크립트 모드
       등)에는 False를 반환해 호출자가 정상적으로 프로그램을 계속 실행하게 한다."""
    try:
        has_update, latest_tag, download_url = check_github_update()
        if not has_update:
            return False
        print(f"[자동업데이트] 새 버전 {latest_tag} 발견 — 현재 버전({APP_VERSION})에서 업데이트를 진행합니다...")
        splash = _show_update_splash(latest_tag)
        ok = _perform_self_update(
            download_url, latest_tag,
            progress_cb=(lambda done, total: _update_splash_progress(splash, done, total)) if splash else None,
        )
        if ok:
            if splash:
                try:
                    splash["root"].destroy()
                except Exception:
                    pass
            return True   # 호출자는 os._exit(0) 등으로 즉시 종료해야 함(배치가 재실행 담당)
        if splash:
            try:
                splash["root"].destroy()
            except Exception:
                pass
        return False
    except Exception as e:
        print(f"[자동업데이트] 예기치 않은 오류(현재 버전으로 계속 실행): {e}")
        return False


# ══════════════════════════════════════════════════════════════
# 티커 검색용 캐시 DB — 이 프로그램이 저장하는 건 이것 하나뿐입니다.
# (관심종목·매매일지·블로그·PDF·공시·수급 등 원본 앱의 다른 기능은 전부 제외)
# ══════════════════════════════════════════════════════════════
def get_db():
    return DB_PATH


def init_db():
    with sqlite3.connect(get_db()) as c:
        c.execute("""CREATE TABLE IF NOT EXISTS ticker_names(
            ticker TEXT PRIMARY KEY, name TEXT, market TEXT, updated TEXT)""")


def db_ticker_count():
    try:
        with sqlite3.connect(get_db()) as c:
            return c.execute("SELECT COUNT(*) FROM ticker_names").fetchone()[0]
    except Exception:
        return 0


def db_save_tickers(rows):
    today = datetime.now().strftime("%Y%m%d")
    with sqlite3.connect(get_db()) as c:
        c.executemany(
            "INSERT OR REPLACE INTO ticker_names VALUES(?,?,?,?)",
            [(t, n, m, today) for t, n, m in rows],
        )


# ══════════════════════════════════════════════════════════════
# 검색 기록 저장소 (⚠️ v117: 로드맵 1단계 — 익명 uid 기준 "최근 본 종목")
# ──────────────────────────────────────────────────────────────
# 위 ticker_names는 "사라져도 그만인 캐시"지만, 이건 다르다 — 사용자가 본 종목 기록은
# Render 같은 무료 웹호스팅이 재배포할 때마다 로컬 디스크를 초기화해도 사라지면 안 되는
# 데이터다. 그래서 DATABASE_URL 환경변수(Neon.tech·Supabase 등 외부 Postgres, 둘 다
# 영구 무료 티어 제공)가 있으면 그쪽에 저장하고, 없으면(로컬 PC 실행 등) 기존 SQLite
# 캐시 파일에 저장해 최소한 "지금 세션"에서는 동작하게 한다. 로그인은 없고, 저장하는
# 값도 종목코드·종목명·시장·조회시각뿐이다 — 이름·이메일 등 개인을 특정할 수 있는
# 정보는 이 단계에서 전혀 받지 않는다(uid는 브라우저에 무작위로 심는 쿠키 값일 뿐).
DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()
_USE_PG = bool(DATABASE_URL) and PG_OK
if DATABASE_URL and not PG_OK:
    print("⚠️ [검색기록] DATABASE_URL은 설정되어 있지만 psycopg2가 설치되어 있지 않아 "
          "검색 기록을 임시로 SQLite에 저장합니다. requirements.txt에 psycopg2-binary를 "
          "추가한 뒤 다시 배포해 주세요.")


def _history_conn():
    """Postgres(DATABASE_URL 있음) 또는 SQLite(없음) 커넥션을 반환한다. 호출부는 두 DB의
       문법 차이(플레이스홀더 %s/?, AUTOINCREMENT 등)만 _USE_PG로 분기하면 된다."""
    if _USE_PG:
        return psycopg2.connect(DATABASE_URL)
    return sqlite3.connect(get_db())


_history_ready = False


def _ensure_history_table():
    """테이블이 아직 준비 안 됐으면(부팅 시 DB가 잠깐 안 붙었던 경우 등) 지금 다시 시도한다.
       실패해도 예외를 밖으로 내지 않는다 — 기록 기능이 멈출 뿐 분석은 계속 된다."""
    global _history_ready
    if _history_ready:
        return True
    try:
        init_history_db()
        _history_ready = True
    except Exception as e:
        print(f"[검색기록] 테이블 준비 실패(나중에 다시 시도): {e}")
    return _history_ready


def init_history_db():
    conn = _history_conn()
    try:
        c = conn.cursor()
        if _USE_PG:
            c.execute("""CREATE TABLE IF NOT EXISTS search_history(
                id SERIAL PRIMARY KEY,
                uid TEXT NOT NULL,
                ticker TEXT NOT NULL,
                name TEXT,
                market TEXT,
                viewed_at TIMESTAMP NOT NULL DEFAULT NOW())""")
            c.execute("CREATE INDEX IF NOT EXISTS idx_history_uid ON search_history(uid, viewed_at DESC)")
        else:
            c.execute("""CREATE TABLE IF NOT EXISTS search_history(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                uid TEXT NOT NULL,
                ticker TEXT NOT NULL,
                name TEXT,
                market TEXT,
                viewed_at TEXT NOT NULL)""")
            c.execute("CREATE INDEX IF NOT EXISTS idx_history_uid ON search_history(uid, viewed_at DESC)")
        conn.commit()
    finally:
        conn.close()


def history_save(uid, ticker, name, market):
    """검색 기록 1건 저장. 실패해도(DB 연결 문제 등) 예외를 밖으로 내보내지 않는다 —
       기록 저장이 실패했다고 종목 분석 자체가 안 되면 안 되기 때문."""
    if not uid or not ticker or not _ensure_history_table():
        return
    try:
        conn = _history_conn()
        try:
            c = conn.cursor()
            if _USE_PG:
                c.execute(
                    "INSERT INTO search_history(uid, ticker, name, market) VALUES(%s,%s,%s,%s)",
                    (uid, ticker, name, market))
            else:
                c.execute(
                    "INSERT INTO search_history(uid, ticker, name, market, viewed_at) VALUES(?,?,?,?,?)",
                    (uid, ticker, name, market, datetime.now().isoformat(timespec="seconds")))
            conn.commit()
        finally:
            conn.close()
    except Exception as e:
        print(f"[검색기록] 저장 실패(무시하고 계속 진행): {e}")


def history_recent(uid, limit=8):
    """이 uid가 최근 본 종목을 최신순으로, 같은 종목은 한 번만 반환한다."""
    if not uid or not _ensure_history_table():
        return []
    try:
        conn = _history_conn()
        try:
            c = conn.cursor()
            # 🐛 [v118] 시각(viewed_at)이 아니라 id(저장 순서, 계속 증가)로 정렬한다 — SQLite는 초 단위로만
            # 저장해서 같은 초에 두 종목을 보면 순서가 뒤섞였다. 종목별 "가장 마지막 기록" 한 줄씩만 고르고
            # 최신순으로 자르는 같은 SQL을 두 DB에서 쓴다(플레이스홀더 %s / ? 만 다름).
            ph = "%s" if _USE_PG else "?"
            c.execute(f"""SELECT ticker, name, market FROM search_history
                          WHERE id IN (SELECT MAX(id) FROM search_history WHERE uid={ph} GROUP BY ticker)
                          ORDER BY id DESC LIMIT {ph}""", (uid, int(limit)))
            return [{"ticker": r[0], "name": r[1], "market": r[2]} for r in c.fetchall()]
        finally:
            conn.close()
    except Exception as e:
        print(f"[검색기록] 조회 실패: {e}")
        return []


def history_clear(uid):
    """🧹 [v121] "최근 본 종목 지우기" — 이 브라우저(uid)의 조회 기록만 지운다."""
    if not uid or not _ensure_history_table():
        return False
    try:
        conn = _history_conn()
        try:
            c = conn.cursor()
            c.execute(f"DELETE FROM search_history WHERE uid={'%s' if _USE_PG else '?'}", (uid,))
            conn.commit()
            return True
        finally:
            conn.close()
    except Exception as e:
        print(f"[검색기록] 삭제 실패: {e}")
        return False


# ══════════════════════════════════════════════════════════════
# 💡 [v121] 매력도 체크(투표) — "이 종목, 지금 사고 싶나요?"
#   buy(👍 사고 싶어요) / watch(🤔 지켜볼래요) / pass(👎 아직은 아니에요) 중 하나.
#   한 브라우저(anon_uid)는 종목마다 한 표 — 다시 누르면 바뀌고, 같은 것을 또 누르면 취소.
#   집계는 최근 VOTE_DAYS일 안에 누른 표만(지금의 분위기를 보여주기 위해).
# ══════════════════════════════════════════════════════════════
VOTE_CHOICES = ("buy", "watch", "pass")
VOTE_DAYS = 30
_votes_ready = False


def _ensure_votes_table():
    global _votes_ready
    if _votes_ready:
        return True
    try:
        conn = _history_conn()
        try:
            c = conn.cursor()
            c.execute("""CREATE TABLE IF NOT EXISTS stock_votes(
                uid TEXT NOT NULL, ticker TEXT NOT NULL, name TEXT, vote TEXT NOT NULL,
                updated_at TEXT NOT NULL, PRIMARY KEY(uid, ticker))""")
            c.execute("CREATE INDEX IF NOT EXISTS idx_votes_ticker ON stock_votes(ticker, updated_at)")
            conn.commit()
            _votes_ready = True
        finally:
            conn.close()
    except Exception as e:
        print(f"[투표] 테이블 준비 실패(나중에 다시 시도): {e}")
    return _votes_ready


def _vote_since():
    return (_now_kst() - timedelta(days=VOTE_DAYS)).strftime("%Y-%m-%d %H:%M:%S")


def vote_summary(ticker, uid=None):
    empty = {"counts": {k: 0 for k in VOTE_CHOICES}, "total": 0, "mine": None, "days": VOTE_DAYS}
    if not _ensure_votes_table():
        return empty
    ph = "%s" if _USE_PG else "?"
    try:
        conn = _history_conn()
        try:
            c = conn.cursor()
            c.execute(f"SELECT vote, COUNT(*) FROM stock_votes WHERE ticker={ph} AND updated_at>={ph} GROUP BY vote",
                      (ticker, _vote_since()))
            counts = {k: 0 for k in VOTE_CHOICES}
            for v, n in c.fetchall():
                if v in counts:
                    counts[v] = int(n)
            mine = None
            if uid:
                c.execute(f"SELECT vote FROM stock_votes WHERE uid={ph} AND ticker={ph}", (uid, ticker))
                row = c.fetchone()
                mine = row[0] if row else None
            return {"counts": counts, "total": sum(counts.values()), "mine": mine, "days": VOTE_DAYS}
        finally:
            conn.close()
    except Exception as e:
        print(f"[투표] 집계 실패: {e}")
        return empty


def vote_cast(uid, ticker, name, vote):
    """vote=None이면 내 표를 취소. 같은 SQL(ON CONFLICT)이 SQLite·Postgres 둘 다에서 동작한다."""
    if not uid or not ticker or not _ensure_votes_table():
        return False
    ph = "%s" if _USE_PG else "?"
    try:
        conn = _history_conn()
        try:
            c = conn.cursor()
            if vote is None:
                c.execute(f"DELETE FROM stock_votes WHERE uid={ph} AND ticker={ph}", (uid, ticker))
            else:
                c.execute(f"""INSERT INTO stock_votes(uid, ticker, name, vote, updated_at) VALUES({ph},{ph},{ph},{ph},{ph})
                              ON CONFLICT(uid, ticker) DO UPDATE SET vote=excluded.vote, name=excluded.name,
                              updated_at=excluded.updated_at""",
                          (uid, ticker, name, vote, _now_kst().strftime("%Y-%m-%d %H:%M:%S")))
            conn.commit()
            return True
        finally:
            conn.close()
    except Exception as e:
        print(f"[투표] 저장 실패: {e}")
        return False


def vote_top(days=7, limit=5):
    """최근 days일 동안 '사고 싶어요'를 가장 많이 받은 종목(홈 화면 '이번 주 매수 관심 TOP')."""
    if not _ensure_votes_table():
        return []
    ph = "%s" if _USE_PG else "?"
    since = (_now_kst() - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
    try:
        conn = _history_conn()
        try:
            c = conn.cursor()
            c.execute(f"""SELECT ticker, MAX(name),
                                 SUM(CASE WHEN vote='buy' THEN 1 ELSE 0 END) AS buys, COUNT(*) AS total
                          FROM stock_votes WHERE updated_at>={ph}
                          GROUP BY ticker HAVING SUM(CASE WHEN vote='buy' THEN 1 ELSE 0 END) > 0
                          ORDER BY buys DESC, total DESC LIMIT {int(limit)}""", (since,))
            return [{"ticker": r[0], "name": r[1], "buys": int(r[2]), "total": int(r[3])} for r in c.fetchall()]
        finally:
            conn.close()
    except Exception as e:
        print(f"[투표] TOP 조회 실패: {e}")
        return []


def history_stats():
    """👥 [v118] 로드맵 '초기 보급' 4순위 — 누적 분석 건수(총 행 수)와 순 방문자 수(uid
       기준 distinct). 별도 카운터 테이블 없이 search_history 하나로 집계한다."""
    if not _ensure_history_table():
        return {"total_analyses": 0, "unique_visitors": 0}
    try:
        conn = _history_conn()
        try:
            c = conn.cursor()
            c.execute("SELECT COUNT(*), COUNT(DISTINCT uid) FROM search_history")
            total, unique = c.fetchone()
            return {"total_analyses": total or 0, "unique_visitors": unique or 0}
        finally:
            conn.close()
    except Exception as e:
        print(f"[검색기록] 통계 조회 실패: {e}")
        return {"total_analyses": 0, "unique_visitors": 0}


_cache_building = False


def _parse_cap_eok(s):
    """네이버 시가총액 문자열('89', '1,234', '3조 4,567' 등)을 억원 정수로 파싱.
       💡 [v107] 네이버 증권 PC 개편(2026-09-11, Next.js 전면 리뉴얼) 대응 코드 공용 헬퍼."""
    s = (s or "").replace("억원", "").replace("억", "").replace("\t", "").replace("\n", "").strip()
    if not s:
        return None
    try:
        if "조" in s:
            a, _, b = s.partition("조")
            jo = float(a.replace(",", "").strip() or 0)
            rest = float(b.replace(",", "").strip() or 0) if b.strip() else 0
            return int(jo * 10000 + rest)
        return int(float(s.replace(",", "").strip()))
    except Exception:
        return None


def _naver_mobile_basic(ticker):
    """💡 [v107] m.stock.naver.com/api/stock/{code}/basic — 2026-09-11 네이버 증권 PC
       개편(Next.js 전면 리뉴얼)으로 finance.naver.com의 기존 서버렌더링 페이지가 전부
       무력화되어(실측 확인: 모든 기존 셀렉터 0건 매치) 새로 채택한 경로. PC와 별개
       제품인 모바일 증권 API는 개편 영향을 받지 않고 그대로 살아있음을 확인했다.
       이름·현재가·등락률·시장구분(코스피/코스닥)·거래 상태를 제공. 실패 시 None."""
    try:
        r = _http().get(f"https://m.stock.naver.com/api/stock/{ticker}/basic", timeout=6)
        if r.status_code != 200:
            return None
        return r.json()
    except Exception:
        return None


def _naver_mobile_integration(ticker):
    """💡 [v107] m.stock.naver.com/api/stock/{code}/integration — PER·PBR·EPS·BPS·배당·
       시총·52주·동일업종 PEER 종목까지 한 번에 제공. 실패 시 None."""
    try:
        r = _http().get(f"https://m.stock.naver.com/api/stock/{ticker}/integration", timeout=6)
        if r.status_code != 200:
            return None
        return r.json()
    except Exception:
        return None


# ══════════════════════════════════════════════════════════════
# ⚡ [v119] 속도 개선 공용 도구 — "종목 분석이 너무 느리다" 대응
# ──────────────────────────────────────────────────────────────
# 실측(삼성전자): 주가 2.0초 + 네이버 기본정보 1.0초 + 네이버 종합정보 1.0초 + FnGuide 1.5초를
# "하나씩 차례로" 불러서 합계 5초 이상 걸렸다(Render의 작은 CPU에서는 더 느림).
#   ① 네 가지를 동시에(병렬로) 불러 가장 느린 하나만큼만 기다린다 → 약 2초
#   ② 결과를 종목별로 잠시 저장(캐시) → 같은 종목을 다시 보면 즉시
#   ③ 데모 종목·많이 보는 종목은 미리 불러 둔다(웹 배포에서 주기적으로 갱신)
#   ④ 같은 연결을 재사용(keep-alive)해 매번 새로 접속하는 시간을 줄인다
# ══════════════════════════════════════════════════════════════
_HTTP_TLS = threading.local()


def _http():
    """스레드마다 하나씩 쓰는 requests.Session — 같은 서버(네이버 등)에 다시 접속할 때
       연결을 재사용해 TLS 접속 시간을 아낀다."""
    s = getattr(_HTTP_TLS, "s", None)
    if s is None:
        s = requests.Session()
        s.headers.update(UA)
        # 🐛 [v120] 네이버가 일시적으로 끊기거나 429/5xx를 주면 잠깐 쉬고 최대 2번 다시 시도
        from urllib3.util.retry import Retry
        retry = Retry(total=2, connect=2, read=1, backoff_factor=0.4,
                      status_forcelist=(429, 500, 502, 503, 504), allowed_methods=frozenset(["GET"]))
        adapter = requests.adapters.HTTPAdapter(pool_connections=8, pool_maxsize=8, max_retries=retry)
        s.mount("https://", adapter)
        s.mount("http://", adapter)
        _HTTP_TLS.s = s
    return s


def _http_fast():
    """⚡ [v122] 재시도 없는 세션 — 주가 소스끼리는 '같은 곳에 다시 시도'보다 '바로 다음 곳으로'가
       빠르다(네이버가 막혔을 때 야후로 넘어가는 시간을 줄임)."""
    s = getattr(_HTTP_TLS, "fast", None)
    if s is None:
        s = requests.Session()
        s.headers.update(UA)
        a = requests.adapters.HTTPAdapter(pool_connections=8, pool_maxsize=8, max_retries=0)
        s.mount("https://", a); s.mount("http://", a)
        _HTTP_TLS.fast = s
    return s


_POOL = ThreadPoolExecutor(max_workers=24, thread_name_prefix="fetch")
_CACHE = {}
_CACHE_LOCK = threading.Lock()
FNGUIDE_WAIT_SEC = 2.5      # 매출 구성(FnGuide)이 이보다 늦으면 이번 화면에선 생략(끝나면 캐시에 저장)


def _now_kst():
    from datetime import timezone
    return datetime.now(timezone(timedelta(hours=9)))


def _analysis_ttl():
    """장중(평일 08:50~15:40)에는 2분, 그 외에는 30분 동안 같은 결과를 재사용한다."""
    n = _now_kst()
    hm = n.hour * 100 + n.minute
    return 120 if (n.weekday() < 5 and 850 <= hm <= 1540) else 1800


def _cache_get(key):
    with _CACHE_LOCK:
        v = _CACHE.get(key)
        if v is None:
            return None
        if v[0] < time.time():
            _CACHE.pop(key, None)
            return None
        return v[1]


def _cache_set(key, val, ttl):
    with _CACHE_LOCK:
        if len(_CACHE) > 3000:
            now = time.time()
            for k in [k for k, v in _CACHE.items() if v[0] < now]:
                _CACHE.pop(k, None)
            if len(_CACHE) > 3000:
                _CACHE.clear()
        _CACHE[key] = (time.time() + ttl, val)


def _fnguide_revenue(ticker):
    """FnGuide 매출 구성 문자열("반도체 (60%), ..."). 자주 안 바뀌므로 하루 동안 캐시한다.
       실패하거나 없으면 ""(1시간 캐시 — 느린 페이지를 매번 다시 두드리지 않기 위함)."""
    hit = _cache_get(("rev", ticker))
    if hit is not None:
        return hit
    text = ""
    try:
        url2 = f"https://comp.fnguide.com/SVO2/ASP/SVD_Main.asp?pGB=1&gicode=A{ticker}"
        r2 = _http().get(url2, timeout=6)
        try:
            soup2 = BeautifulSoup(r2.content.decode("utf-8", "replace"), "lxml")
        except Exception:
            soup2 = BeautifulSoup(r2.content.decode("utf-8", "replace"), "html.parser")
        ratio_th = soup2.find("th", string=lambda x: x and ("매출비중" in x or "매출비율" in x or "매출구성" in x))
        if ratio_th:
            tbody = ratio_th.find_parent("table").find("tbody")
            if tbody:
                revs = []
                for tr in tbody.find_all("tr"):
                    tds = tr.find_all(["th", "td"])
                    if len(tds) >= 2:
                        nm = tds[0].text.strip()
                        ratio = tds[-1].text.strip()
                        if nm and ratio and nm not in ["계", "합계", "총계"] and ratio != "-":
                            revs.append(f"{nm} ({ratio}%)")
                text = ", ".join(revs)
    except Exception as e:
        print(f"[기업개요] FnGuide 조회 오류(무시): {e}")
    _cache_set(("rev", ticker), text, 86400 if text else 3600)
    return text


# ══════════════════════════════════════════════════════════════
# 📑 [v121] 재무정보 — 네이버 모바일 증권 API(연간 3년 + 다음 해 추정, 분기 5개 + 다음 분기 추정)
#   단위: 금액은 억원, 비율은 %, 주당 값은 원. "(E)"는 증권사 컨센서스 추정치.
#   재무제표는 자주 바뀌지 않으므로 12시간 동안 재사용한다.
# ══════════════════════════════════════════════════════════════
FIN_ROWS = ["매출액", "영업이익", "당기순이익", "영업이익률", "순이익률", "ROE", "부채비율", "당좌비율",
            "유보율", "EPS", "BPS", "주당배당금", "PER", "PBR"]


def _to_num(v):
    try:
        v = str(v).replace(",", "").strip()
        return None if v in ("", "-", "N/A", "None") else float(v)
    except Exception:
        return None


def _naver_finance(ticker, period="annual"):
    key = ("fin", period, ticker)
    hit = _cache_get(key)
    if hit is not None:
        return hit or None
    if _naver_unhealthy():
        return None                 # ⚡ [v122] 네이버 불안정 — 새로 요청하지 않음(캐시에 없으면 생략)
    out = None
    try:
        r = _http().get(f"https://m.stock.naver.com/api/stock/{ticker}/finance/{period}", timeout=6)
        if r.status_code == 200:
            info = (r.json() or {}).get("financeInfo") or {}
            cols = info.get("trTitleList") or []
            rows = {}
            for row in info.get("rowList") or []:
                t = (row.get("title") or "").strip()
                if t in FIN_ROWS:
                    rows[t] = [_to_num((row.get("columns") or {}).get(c.get("key"), {}).get("value")) for c in cols]
            if cols and rows:
                out = {"periods": [{"title": (c.get("title") or "").rstrip("."), "estimate": c.get("isConsensus") == "Y"}
                                   for c in cols],
                       # 순서가 중요해서(매출→이익→비율…) dict가 아니라 목록으로 둔다 — JSON으로 오가며 키가 정렬되는 것 방지
                       "rows": [{"name": k, "values": rows[k]} for k in FIN_ROWS if k in rows]}
    except Exception as e:
        print(f"[재무] {ticker} {period} 조회 오류(무시): {e}")
    _cache_set(key, out or {}, 12 * 3600 if out else 600)
    return out


# ══════════════════════════════════════════════════════════════
# 📰 [v121] 관련 뉴스 — 최근 14일(2주) 이내 기사만, 같은 사건을 다룬 기사 묶음은 대표 1건 + 관련 건수
# ══════════════════════════════════════════════════════════════
NEWS_DAYS = 14
NEWS_LIMIT = 12


def _naver_news(ticker):
    import html as _html
    cutoff = (_now_kst() - timedelta(days=NEWS_DAYS)).strftime("%Y%m%d%H%M")
    items = []
    try:
        for page in (1, 2):
            r = _http().get(f"https://m.stock.naver.com/api/news/stock/{ticker}",
                            params={"pageSize": 20, "page": page}, timeout=6)
            if r.status_code != 200:
                break
            groups = r.json() or []
            reached_old = False
            for grp in groups:
                it = (grp.get("items") or [None])[0]
                if not it:
                    continue
                dt = str(it.get("datetime") or "")
                if dt < cutoff:
                    reached_old = True
                    continue
                items.append({
                    "datetime": dt,
                    "date": f"{dt[4:6]}.{dt[6:8]} {dt[8:10]}:{dt[10:12]}" if len(dt) >= 12 else dt,
                    "press": it.get("officeName") or "",
                    "title": _html.unescape(it.get("titleFull") or it.get("title") or "").strip(),
                    "url": it.get("mobileNewsUrl") or f"https://n.news.naver.com/mnews/article/{it.get('officeId')}/{it.get('articleId')}",
                    "related": max(0, int(grp.get("total") or 1) - 1),
                })
            if reached_old or len(items) >= NEWS_LIMIT or len(groups) < 20:
                break
    except Exception as e:
        print(f"[뉴스] {ticker} 조회 오류(무시): {e}")
    items.sort(key=lambda x: x["datetime"], reverse=True)
    return items[:NEWS_LIMIT]


def _fetch_all_parallel(ticker, need_price=True):
    """주가·네이버 기본정보·네이버 종합정보·FnGuide 매출구성을 동시에 불러온다.
       FnGuide만 FNGUIDE_WAIT_SEC까지만 기다리고, 늦으면 이번엔 빈 값으로 넘어간다."""
    t0 = time.time()
    f_price = _POOL.submit(get_price_data, ticker) if need_price else None
    # ⚡ [v122] 네이버가 최근 계속 실패 중이면 네이버 전용 정보(기본정보·재무·뉴스)는 요청하지 않는다
    # — 막힌 곳을 기다리느라 주가(야후)까지 늦어지지 않게. 캐시에 남은 재무는 그대로 쓴다.
    skip_naver = _naver_unhealthy()
    noop = _POOL.submit(lambda: None)
    f_basic = noop if skip_naver else _POOL.submit(_naver_mobile_basic, ticker)
    f_integ = noop if skip_naver else _POOL.submit(_naver_mobile_integration, ticker)
    rev = _cache_get(("rev", ticker))
    f_rev = None if (rev is not None or skip_naver) else _POOL.submit(_fnguide_revenue, ticker)
    f_fin_a = _POOL.submit(_naver_finance, ticker, "annual")      # 📑 [v121] (캐시 있으면 즉시)
    f_fin_q = _POOL.submit(_naver_finance, ticker, "quarter")
    f_news = noop if skip_naver else _POOL.submit(_naver_news, ticker)   # 📰 [v121]

    def _res(f, timeout):
        try:
            return f.result(timeout=max(0.05, timeout))
        except Exception:
            return None
    price = _res(f_price, 45) if f_price else None
    # 주가를 야후에서 받았다면 네이버가 불안정하다는 뜻 — 부가정보는 최대 3초만 더 기다린다.
    naver_slow = bool(f_price) and PRICE_LAST_SOURCE.get(ticker) == "yahoo"
    deadline = time.time() + (3 if naver_slow else 10)
    left = lambda: deadline - time.time()
    basic = _res(f_basic, left())
    integ = _res(f_integ, left())
    if f_rev is not None:
        rev = _res(f_rev, min(left(), max(0.2, FNGUIDE_WAIT_SEC - (time.time() - t0)))) or ""
    rev = rev or ""
    extra = {"fin_annual": _res(f_fin_a, left() + 2), "fin_quarter": _res(f_fin_q, left() + 2),
             "news": _res(f_news, left() + 2) or [],
             "partial": skip_naver or naver_slow, "price_source": PRICE_LAST_SOURCE.get(ticker)}
    return price, basic, integ, rev, extra


# 🐛 [v110] 이 자리에 있던 _naver_overall_info_text()는 실측 결과 회사 소개 문단이
# 아니라 미니 시세 위젯(전일가·PER·EPS 등 숫자 나열)을 반환하는 것으로 확인되어
# 제거했다 — 기업개요 흐름은 이제 증권사 리포트 제목 → AI 분석 추출 두 단계만 쓴다
# (get_company_details_and_fundamentals 참고).



def _naver_mobile_market_ranking(market: str, max_pages: int = 15, page_size: int = 60):
    """💡 [v107] m.stock.naver.com/api/stocks/marketValue/{KOSPI|KOSDAQ} — 개편 이후
       확인된 전종목 시가총액 순위 API. 기존 finance.naver.com/sise/sise_market_sum.naver
       스크래핑(개편으로 완전히 무력화)을 대체. 반환: [(code, name, market), ...]"""
    rows = []
    mk = (market or "").upper()
    if mk not in ("KOSPI", "KOSDAQ"):
        return rows
    for page in range(1, max_pages + 1):
        try:
            r = requests.get(
                f"https://m.stock.naver.com/api/stocks/marketValue/{mk}",
                params={"page": page, "pageSize": page_size}, headers=UA, timeout=8
            )
            if r.status_code != 200:
                break
            data = r.json()
            stocks = data.get("stocks") or []
            if not stocks:
                break
            for s in stocks:
                tk = str(s.get("itemCode", "")).strip().zfill(6)
                if tk:
                    rows.append((tk, s.get("stockName", ""), mk))
        except Exception as e:
            print(f"[티커목록] 네이버모바일 {mk} page={page} 오류(무시): {e}")
            break
    return rows


def _build_ticker_list_naver():
    """💡 [v107] fdr.StockListing('KRX')가 data.krx.co.kr에 의존하는데, 이 도메인이
       IP 차단·일시 장애 등으로 막히면 검색용 종목목록을 아예 못 채워 앱을 쓸 수 없게 된다
       (분석 자체(get_price_data)는 fdr.DataReader가 기본적으로 네이버를 쓰므로 영향 없음 —
       막히는 건 오직 '전체 종목 목록 긁어오기'뿐). KRX를 전혀 거치지 않는 네이버 모바일
       증권 API로 대체한다(2026-09-11 PC 개편 이후에도 살아있음을 확인한 경로)."""
    rows = []
    for market in ("KOSPI", "KOSDAQ"):
        rows.extend(_naver_mobile_market_ranking(market, max_pages=15))
    return rows


def build_ticker_cache(force=False):
    """상장종목 목록으로 검색용 캐시를 채운다(무료, 로그인 불필요).
       1순위: FinanceDataReader → 2순위: 네이버금융 시가총액 페이지 직접 크롤링."""
    global _cache_building
    if _cache_building:
        return
    _cache_building = True
    try:
        if not (force or db_ticker_count() < 1000):
            return

        rows = []
        if FDR_OK:
            try:
                df = fdr.StockListing("KRX")
                for _, r in df.iterrows():
                    code = str(r.get("Code", r.get("Symbol", ""))).strip()
                    if not code:
                        continue
                    rows.append((code.zfill(6), str(r.get("Name", "")).strip(),
                                 str(r.get("Market", "—")).strip()))
            except Exception as e:
                print(f"[티커목록] FinanceDataReader 조회 실패(네이버로 대체 시도): {e}")

        if len(rows) < 500:
            print("[티커목록] 네이버금융에서 종목 목록을 직접 가져옵니다(약 20~30초 소요)...")
            naver_rows = _build_ticker_list_naver()
            if naver_rows:
                rows = naver_rows

        if rows:
            db_save_tickers(rows)
            print(f"[티커목록] {len(rows)}종목 갱신 완료")
        else:
            print("[티커목록] 갱신 실패 — 잠시 후 상단의 [🔄 종목목록 갱신]을 다시 눌러주세요. "
                  "(그동안도 종목코드를 직접 입력하면 분석은 정상적으로 됩니다)")
    finally:
        _cache_building = False


def search_tickers(q: str):
    q = (q or "").strip()
    if not q:
        return []
    digits = "".join(filter(str.isdigit, q))
    q_padded = digits.zfill(6) if digits else ""
    q_no_space = q.replace(" ", "")
    try:
        with sqlite3.connect(get_db()) as c:
            rows = c.execute(
                """
                SELECT ticker, name, market FROM ticker_names
                WHERE name LIKE ? OR REPLACE(name,' ','') LIKE ? OR ticker LIKE ? OR ticker = ?
                ORDER BY (ticker = ?) DESC, (name = ?) DESC, LENGTH(name) ASC LIMIT 15
                """,
                (f"%{q}%", f"%{q_no_space}%", f"%{q}%", q_padded, q_padded, q),
            ).fetchall()
        return [{"ticker": r[0], "name": r[1], "market": r[2]} for r in rows]
    except Exception:
        return []


def normalize_ticker(raw: str) -> str:
    """🐛 [v103] "0011T0(채비) 같은 코스닥 종목을 못 가져온다" — 원인은 종목코드를
       "".join(filter(str.isdigit, ticker)).zfill(6) 로 정규화하던 부분. 2024년 KRX
       종목코드 체계 개편 이후 일부 종목은 6자리 중 한 자리가 숫자가 아니라 영문자인
       코드를 쓰는데(예: 0011T0), 숫자만 남기고 문자를 지워버려서 "00110"이라는
       존재하지 않는 코드로 조회를 시도해 실패했다. 순수 숫자 코드(6자리 미만이면
       0으로 채움)와 신규 영숫자 혼용 코드를 모두 지원하도록 수정."""
    s = (raw or "").strip().upper()
    s = re.sub(r"[^0-9A-Z]", "", s)
    if not s:
        return ""
    if s.isdigit():
        return s.zfill(6)
    return s


def get_ticker_info(ticker: str):
    try:
        with sqlite3.connect(get_db()) as c:
            row = c.execute("SELECT name, market FROM ticker_names WHERE ticker=?",
                             (ticker,)).fetchone()
            if row:
                return row[0], row[1]
    except Exception:
        pass
    return None, None


def get_ticker_name_live(ticker: str):
    """💡 [v107] 검색 캐시가 아직 안 채워졌어도(예: 목록 갱신이 실패한 상황) 종목코드를
       직접 입력하면 분석이 되도록, 네이버 모바일 증권 API에서 실제 종목명을 즉석에서
       가져온다(2026-09-11 PC 개편과 무관한 안정적 경로). 실패해도 절대 예외를 던지지
       않고 None을 반환(호출부가 코드로 대체 표시)."""
    try:
        return _name_from_basic(_naver_mobile_basic(ticker))
    except Exception:
        return None, None


def _name_from_basic(d):
    """네이버 basic 응답에서 (종목명, 시장). ⚡ [v119] 분석 때 이미 받아온 basic을 재사용해
       이름을 얻으려고 분리했다(같은 요청을 두 번 보내지 않음)."""
    if not d:
        return None, None
    name = d.get("stockName") or None
    market = None
    ext = (d.get("stockExchangeType") or {}).get("nameEng", "").upper()
    if ext in ("KOSPI", "KOSDAQ", "KONEX"):
        market = ext
    return name, market


def _v(x, default=None):
    try:
        f = float(x)
        return default if (math.isnan(f) or math.isinf(f)) else f
    except Exception:
        return default


# ══════════════════════════════════════════════════════════════
# 가격 + 기술적분석 — FinanceDataReader만 사용(무료·로그인 불필요).
# 원본 앱의 종목분석 핵심 로직을 그대로 이식했습니다(수급/재무/공시/뉴스 등
# KRX 로그인·DART API 키가 필요한 부분은 이 공개판에서 전부 제외했습니다).
# ══════════════════════════════════════════════════════════════
# ══════════════════════════════════════════════════════════════
# 🐛 [v120] 주가 데이터 3단계 확보 — "주가 데이터를 가져오지 못했습니다" 대응
# ──────────────────────────────────────────────────────────────
# FinanceDataReader는 자체 대기시간(timeout)이 없어, 네이버가 서버(Render) 요청에 늦게
# 답하면 끝없이 기다리다 실패했다. 이제 서로 다른 네이버 서버 세 곳을 차례로 시도한다.
#   ① api.stock.naver.com 일봉 JSON(가볍고 빠름, 8초 제한)
#   ② FinanceDataReader(fchart.stock.naver.com, 12초 제한)
#   ③ fchart XML 직접 호출(8초 제한)
# 어느 쪽이든 같은 모양의 표(Open·High·Low·Close·Volume, 날짜 인덱스)로 맞춰 넘긴다.
# ══════════════════════════════════════════════════════════════
_FDR_POOL = ThreadPoolExecutor(max_workers=6, thread_name_prefix="fdr")
PRICE_LAST_SOURCE = {}   # 종목별로 마지막에 성공한 소스(진단용)


def _ohlcv_frame(rows):
    """[(yyyymmdd, open, high, low, close, volume), ...] → FDR과 같은 모양의 DataFrame."""
    if not rows:
        return None
    df = pd.DataFrame(rows, columns=["Date", "Open", "High", "Low", "Close", "Volume"])
    df["Date"] = pd.to_datetime(df["Date"], format="%Y%m%d")
    df = df.set_index("Date").sort_index()
    for c in ["Open", "High", "Low", "Close", "Volume"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df = df[df["Close"] > 0]
    return df if len(df) else None


def _ohlcv_naver_api(ticker, start):
    s0 = start.replace("-", "") + "0000"
    e0 = datetime.now().strftime("%Y%m%d") + "2359"
    r = _http_fast().get(f"https://api.stock.naver.com/chart/domestic/item/{ticker}/day",
                         params={"startDateTime": s0, "endDateTime": e0}, timeout=(3.05, 6))
    r.raise_for_status()
    data = r.json()
    return _ohlcv_frame([(d["localDate"], d.get("openPrice"), d.get("highPrice"), d.get("lowPrice"),
                          d.get("closePrice"), d.get("accumulatedTradingVolume")) for d in data if d.get("localDate")])


def _ohlcv_fdr(ticker, start):
    if not FDR_OK:
        return None
    f = _FDR_POOL.submit(fdr.DataReader, ticker, start)
    df = f.result(timeout=10)
    return df if (df is not None and not df.empty) else None


def _ohlcv_fchart(ticker, start):
    days = (datetime.now() - datetime.strptime(start, "%Y-%m-%d")).days
    r = _http_fast().get("https://fchart.stock.naver.com/sise.nhn",
                         params={"symbol": ticker, "timeframe": "day", "count": max(days, 60), "requestType": 0},
                         timeout=(3.05, 6))
    r.raise_for_status()
    rows = []
    for m_ in re.finditer(r'data="([^"]+)"', r.content.decode("euc-kr", "replace")):
        parts = m_.group(1).split("|")
        if len(parts) >= 6:
            rows.append(tuple(parts[:6]))
    df = _ohlcv_frame(rows)
    return df[df.index >= pd.Timestamp(start)] if df is not None else None


def _ohlcv_yahoo(ticker, start):
    """🌐 [v122] 야후 파이낸스 — 네이버와 완전히 별개인 해외 서비스라, 네이버가 서버(Render) 요청을
       막거나 느릴 때 대신 쓴다. 코스피는 종목코드.KS, 코스닥은 종목코드.KQ(0011T0 같은 영문 코드도 됨).
       장중에는 약 15~20분 늦은 시세일 수 있다."""
    from datetime import timezone
    _, market = get_ticker_info(ticker)
    # "KOSDAQ GLOBAL"처럼 붙은 이름도 코스닥으로 본다(잘못된 접미사로 조회하면 야후가 옛 상장 기록을 줄 수 있음)
    syms = [f"{ticker}.KQ", f"{ticker}.KS"] if "KOSDAQ" in (market or "").upper() else [f"{ticker}.KS", f"{ticker}.KQ"]
    kst = timezone(timedelta(hours=9))

    def _get(sym, rng):
        r = _http_fast().get(f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}",
                             params={"range": rng, "interval": "1d"}, timeout=(3.05, 6))
        if r.status_code == 404:
            return None                    # 시장 접미사가 틀린 경우 — 다른 쪽으로 다시
        r.raise_for_status()
        res = ((r.json() or {}).get("chart") or {}).get("result")
        if not res:
            return None
        res = res[0]
        q = (((res.get("indicators") or {}).get("quote")) or [{}])[0]
        rows = []
        for i, t in enumerate(res.get("timestamp") or []):
            try:
                c = q["close"][i]
                if c is None:
                    continue
                rows.append((datetime.fromtimestamp(t, tz=kst).strftime("%Y%m%d"),
                             q["open"][i], q["high"][i], q["low"][i], c, q["volume"][i] or 0))
            except (KeyError, IndexError, TypeError):
                continue
        return _ohlcv_frame(rows)

    for sym in syms:
        df = _get(sym, "2y")
        if df is None:
            continue
        # 야후의 2년치 일봉에는 "오늘" 봉이 빠져 있는 경우가 있어(1개월치에는 있음), 최근 며칠을 덧붙인다.
        today = _now_kst().strftime("%Y%m%d")
        if df.index[-1].strftime("%Y%m%d") < today:
            try:
                recent = _get(sym, "5d")
                if recent is not None:
                    df = pd.concat([df, recent])
            except Exception:
                pass
        df = df[~df.index.duplicated(keep="last")].sort_index()
        # 마지막 거래일이 10일 넘게 지난 기록은 다른 시장의 옛 상장 기록일 수 있으니 버리고 다른 접미사로 시도
        if (pd.Timestamp(_now_kst().date()) - df.index[-1]).days > 10:
            continue
        return df[df.index >= pd.Timestamp(start)]
    return None


# 순서: 네이버(가장 빠름) → 야후(네이버와 무관한 다른 회사) → FDR(네이버) → fchart(네이버)
_PRICE_SOURCES = (("naver_api", _ohlcv_naver_api), ("yahoo", _ohlcv_yahoo),
                  ("fdr", _ohlcv_fdr), ("fchart", _ohlcv_fchart))

# ⚡ [v122] 소스 건강 상태 — 5분 안에 연결·시간초과 오류가 2번 나면 그 소스는 3분 동안 뒤로 미룬다
# ("빈 데이터"처럼 종목 탓인 실패는 세지 않음). 네이버가 막힌 동안 매번 시간초과를 기다리지 않게.
_SRC_HEALTH = {}
_SRC_LOCK = threading.Lock()


def _src_ok(name):
    with _SRC_LOCK:
        h = _SRC_HEALTH.get(name)
        return not h or h.get("until", 0) < time.time()


def _src_report(name, ok):
    now = time.time()
    with _SRC_LOCK:
        if ok:
            _SRC_HEALTH.pop(name, None)
            return
        h = _SRC_HEALTH.setdefault(name, {"fails": [], "until": 0})
        h["fails"] = [t for t in h["fails"] if now - t < 300] + [now]
        if len(h["fails"]) >= 2:
            if h["until"] < now:
                print(f"[주가] 소스 '{name}' 연속 실패 — 3분 동안 뒤로 미룹니다")
            h["until"] = now + 180


def _naver_unhealthy():
    """네이버 주가 API가 최근 연속 실패 중이면 True — 이때는 재무·뉴스 등 네이버 전용 정보를 건너뛴다."""
    return not _src_ok("naver_api")


def _fetch_ohlcv(ticker, start):
    """주가 소스를 차례로 시도해 처음 성공한 표를 돌려준다. 최근 계속 실패한 소스는 맨 뒤로 보내고,
       실패 사유는 Render 로그에 남긴다."""
    order = [x for x in _PRICE_SOURCES if _src_ok(x[0])] + [x for x in _PRICE_SOURCES if not _src_ok(x[0])]
    errors = []
    for name, fn in order:
        t0 = time.time()
        try:
            df = fn(ticker, start)
            _src_report(name, True)
            if df is not None and len(df) >= 2:
                PRICE_LAST_SOURCE[ticker] = name
                if errors:
                    print(f"[주가] {ticker}: {name}로 대체 성공 ({time.time()-t0:.1f}s) — 앞선 실패: {'; '.join(errors)}")
                return df
            errors.append(f"{name}=빈 데이터")
        except Exception as e:
            _src_report(name, False)
            errors.append(f"{name}={type(e).__name__}({time.time()-t0:.1f}s)")
    print(f"[주가] {ticker}: 모든 소스 실패 — {'; '.join(errors)}")
    return None


def get_price_data(ticker: str):
    try:
        st = (datetime.now() - timedelta(days=420)).strftime("%Y-%m-%d")
        df = _fetch_ohlcv(ticker, st)
        if df is None or df.empty:
            return None

        df = df.rename(columns={"Open": "O", "High": "H", "Low": "L",
                                 "Close": "C", "Volume": "V", "Change": "P"})
        if "P" in df.columns:
            df["P"] = df["P"] * 100
        else:
            df["P"] = df["C"].pct_change() * 100

        df = df.dropna(subset=["C"])
        n = len(df)
        if n < 2:
            return None

        is_ipo = n < 60
        w5, w20, w60, w14 = min(5, n), min(20, n), min(60, n), min(14, n)

        df["ma5"] = df["C"].rolling(w5, min_periods=1).mean()
        df["ma20"] = df["C"].rolling(w20, min_periods=1).mean()
        df["ma60"] = df["C"].rolling(w60, min_periods=1).mean()
        df["ma50"] = df["C"].rolling(min(50, n), min_periods=1).mean()
        df["ma100"] = df["C"].rolling(min(100, n), min_periods=1).mean()
        df["vol_ma20"] = df["V"].rolling(w20, min_periods=1).mean()
        df["std"] = df["C"].rolling(w20, min_periods=2).std().fillna(0)
        df["upper"] = df["ma20"] + (df["std"] * 2)
        df["lower"] = df["ma20"] - (df["std"] * 2)

        d_diff = df["C"].diff()
        g = d_diff.clip(lower=0).rolling(w14, min_periods=1).mean()
        l = (-d_diff.clip(upper=0)).rolling(w14, min_periods=1).mean()
        df["rsi"] = 100 - 100 / (1 + g / l.replace(0, np.nan))
        df.loc[(l == 0) & (g > 0), "rsi"] = 100.0

        lat = df.iloc[-1]
        prev = df.iloc[-2] if n > 1 else lat
        price = int(lat["C"])
        h52, l52 = int(df["H"].max()), int(df["L"].min())
        pos52 = round((price - l52) / max(h52 - l52, 1) * 100, 1) if h52 != l52 else 50

        _vol_row = lat if int(_v(lat["V"], 0)) > 0 else prev
        vr = round(int(_v(_vol_row["V"], 0)) / max(_v(_vol_row["vol_ma20"], 1), 1), 2)
        ma5, ma20, ma60 = _v(lat["ma5"]), _v(lat["ma20"]), _v(lat["ma60"])
        rsi = round(_v(lat["rsi"], 50.0), 1)
        dpct = round(_v(lat["P"], 0.0), 2)

        ma20d = round((price - ma20) / max(ma20, 1) * 100, 1) if ma20 else 0.0
        if n >= 60 and ma5 and ma20 and ma60:
            align = "정배열" if ma5 > ma20 > ma60 else ("역배열" if ma5 < ma20 < ma60 else "혼재")
        elif n >= 5 and ma5 and ma20:
            align = "단기상승" if ma5 > ma20 else ("단기하락" if ma5 < ma20 else "혼재")
        else:
            align = "데이터부족"

        tech_score = (
            (2 if ma20d > 5 else 1 if ma20d > 1 else 0 if ma20d > -3 else -1 if ma20d > -8 else -2)
            + (2 if vr >= 3 else 1 if vr >= 1.5 else 0 if vr >= 0.8 else -1)
            + (2 if pos52 >= 85 else 1 if pos52 >= 60 else 0 if pos52 >= 35 else -1)
        )

        lower_last = _v(df["lower"].dropna().values[-1]) if len(df["lower"].dropna()) > 0 else 0
        upper_last = _v(df["upper"].dropna().values[-1]) if len(df["upper"].dropna()) > 0 else 0

        theory = []
        if is_ipo:
            ipo_ret = round((price / int(df.iloc[0]["C"]) - 1) * 100, 1) if int(df.iloc[0]["C"]) else 0
            theory.append(f"🆕 <b>[신규상장 종목]</b> 상장 후 약 <b>{n}거래일</b> 경과. "
                          f"상장가 대비 현재 <b>{'▲+' if ipo_ret >= 0 else '▼'}{ipo_ret}%</b>. "
                          f"데이터 부족으로 일부 지표가 단기 기준으로 계산됩니다.")
        is_up = lat["C"] >= lat["O"]
        if vr >= 2.0:
            if is_up:
                theory.append(f"✅ <b>[대량 매집 포착 (와이코프 기법)]</b> 평소 대비 {vr}배의 대량 거래를 "
                              f"동반하며 주가가 상승(양봉)했습니다. 스마트 머니의 강력한 '매집' 세력이 "
                              f"유입되었을 확률이 매우 높아 단기 상승 관점입니다.")
            else:
                theory.append(f"⚠️ <b>[물량 분산/투매 포착 (와이코프 기법)]</b> 평소 대비 {vr}배의 대량 거래가 "
                              f"터지며 주가가 하락(음봉)했습니다. 주도 세력의 물량 이탈 리스크가 있습니다.")
        elif vr <= 0.5:
            theory.append(f"➖ <b>[거래량 분석]</b> 거래량이 평소의 반토막 수준({vr}배)으로, "
                          f"시장의 관심이 극도로 줄어든 '소외/관망' 구간입니다.")

        wave_txt = ("이평선이 상승 중이므로 '상승 파동'이 진행 중일 가능성이 있습니다."
                    if ma5 and ma20 and ma5 > ma20 else
                    "현재 '단기 하락 파동(조정 파동)'이 진행 중일 가능성이 높습니다.")
        theory.append(f"<b>1. 엘리어트 파동 이론</b><br> - {wave_txt}")

        if align == "정배열":
            gr_txt = "이동평균선이 정배열되어 강력한 '매수(상승)' 신호를 나타냅니다."
        elif align == "역배열":
            gr_txt = "역배열 상태로 '매도(하락)' 구간입니다. 바닥 확인이 필요합니다."
        else:
            gr_txt = "이평선들이 얽혀있는 '횡보/조정' 구간입니다."
        theory.append(f"<b>2. 그랜빌의 법칙</b><br> - {gr_txt}")

        if lower_last and price <= lower_last * 1.02:
            bb_txt = "주가가 하단 밴드에 도달하여 '과매도' 상태이며, 지지선 반등을 기대해볼 수 있습니다."
        elif upper_last and price >= upper_last * 0.98:
            bb_txt = "주가가 상단 밴드에 도달하여 '과매수' 상태이며, 단기 조정을 받을 가능성이 있습니다."
        else:
            bb_txt = "주가가 상하단 밴드 내에서 안정적인 흐름을 이어가고 있습니다."
        theory.append(f"<b>3. 볼린저 밴드</b><br> - {bb_txt}")

        if rsi >= 70:
            rsi_txt = f"수치가 {rsi}로 70 이상인 '과매수' 구간입니다. 차익 실현 매물이 출회될 수 있습니다."
        elif rsi <= 30:
            rsi_txt = f"수치가 {rsi}로 30 이하인 '과매도' 구간입니다. 기술적 반등을 노려볼 만한 자리입니다."
        else:
            rsi_txt = f"수치가 {rsi}로 중립적인 상태입니다."
        theory.append(f"<b>4. 상대강도지수 (RSI)</b><br> - {rsi_txt}")

        # ── 일목균형표(Ichimoku) 구름 — [v113] 신설 ──
        # 전환선(9일)·기준선(26일)은 당일 값을 그대로, 구름(선행스팬 A/B)은 정의상
        # "26일 뒤 미래"에 표시하는 지표이므로 나중에 26거래일만큼 앞으로 밀어(shift) 그린다.
        _ich_w9, _ich_w26, _ich_w52 = min(9, n), min(26, n), min(52, n)
        df["tenkan"] = (df["H"].rolling(_ich_w9, min_periods=1).max()
                         + df["L"].rolling(_ich_w9, min_periods=1).min()) / 2
        df["kijun"] = (df["H"].rolling(_ich_w26, min_periods=1).max()
                        + df["L"].rolling(_ich_w26, min_periods=1).min()) / 2
        df["senkou_a_raw"] = (df["tenkan"] + df["kijun"]) / 2
        df["senkou_b_raw"] = (df["H"].rolling(_ich_w52, min_periods=1).max()
                               + df["L"].rolling(_ich_w52, min_periods=1).min()) / 2
        _ich_disp = min(26, n)
        df["senkou_a_disp"] = df["senkou_a_raw"].shift(_ich_disp)
        df["senkou_b_disp"] = df["senkou_b_raw"].shift(_ich_disp)

        # ── 매물대 분석 (Volume Profile, 최근 60거래일) ──
        vp_result = {}
        try:
            VP_BUCKETS = 30
            VP_DAYS = min(60, len(df))
            vp_df = df.iloc[-VP_DAYS:]
            vp_hi_val = float(vp_df["H"].max())
            vp_lo_val = float(vp_df["L"].min())
            vp_range_v = vp_hi_val - vp_lo_val
            if vp_range_v > 10:
                bk_step = vp_range_v / VP_BUCKETS
                bk_vols = np.zeros(VP_BUCKETS)
                for i in range(len(vp_df)):
                    vol = float(vp_df.iloc[i]["V"]) or 0
                    hi_ = float(vp_df.iloc[i]["H"])
                    lo_ = float(vp_df.iloc[i]["L"])
                    b0_ = max(0, int((lo_ - vp_lo_val) / bk_step))
                    b1_ = min(VP_BUCKETS - 1, int((hi_ - vp_lo_val) / bk_step))
                    sp_ = b1_ - b0_ + 1
                    for b_ in range(b0_, b1_ + 1):
                        bk_vols[b_] += vol / sp_

                poc_idx = int(np.argmax(bk_vols))
                poc_price = round(vp_lo_val + (poc_idx + 0.5) * bk_step)

                total_vol_vp = float(np.sum(bk_vols))
                target_vp = total_vol_vp * 0.70
                va_vol = float(bk_vols[poc_idx])
                vl_idx = vh_idx = poc_idx
                while va_vol < target_vp and (vl_idx > 0 or vh_idx < VP_BUCKETS - 1):
                    add_lo_ = float(bk_vols[vl_idx - 1]) if vl_idx > 0 else 0
                    add_hi_ = float(bk_vols[vh_idx + 1]) if vh_idx < VP_BUCKETS - 1 else 0
                    if add_lo_ == 0 and add_hi_ == 0:
                        break
                    if add_lo_ >= add_hi_ and vl_idx > 0:
                        vl_idx -= 1
                        va_vol += add_lo_
                    elif vh_idx < VP_BUCKETS - 1:
                        vh_idx += 1
                        va_vol += add_hi_
                    else:
                        vl_idx -= 1
                        va_vol += add_lo_

                val_price = round(vp_lo_val + vl_idx * bk_step)
                vah_price = round(vp_lo_val + (vh_idx + 1) * bk_step)
                poc_diff = round((price - poc_price) / max(poc_price, 1) * 100, 1)
                poc_diff_str = f"{'▲+' if poc_diff >= 0 else '▼'}{abs(poc_diff)}%"

                if price > vah_price:
                    va_pos = "가치 영역(핵심 거래 구간) 상단을 돌파한 강세 구간"
                    vp_color = "강세"
                elif price < val_price:
                    va_pos = "가치 영역(핵심 거래 구간) 하단 아래로 이탈한 약세 구간"
                    vp_color = "약세"
                else:
                    va_pos = "가치 영역(핵심 거래 구간) 안에서 거래 중인 중립 구간"
                    vp_color = "중립"

                vp_result = {
                    "poc": poc_price, "vah": vah_price, "val": val_price,
                    "poc_diff_str": poc_diff_str, "va_pos": va_pos, "vp_color": vp_color,
                }
        except Exception as _vpe:
            print(f"[매물대] 계산 오류(무시): {_vpe}")

        # 🐛 [v113] 요청("60일 거래기준")을 넉넉히 담으면서, 구름이 26일 앞으로도
        #    투영되는 점을 감안해 화면 표시 구간을 90일→120일로 넓혔다.
        cd = df.tail(min(120, n))

        def _si(arr):
            return [None if _v(x) is None else float(x) for x in arr]

        # 구름(선행스팬)은 미래로도 그려지므로, 화면에 보여줄 날짜 축을 실제 거래일보다
        # _ich_disp(최대 26)만큼 미래 영업일로 늘려서 함께 계산해둔다.
        cloud_future_dates = []
        cloud_a_future, cloud_b_future = [], []
        try:
            future_idx = pd.bdate_range(start=cd.index[-1], periods=_ich_disp + 1)[1:]
            cloud_future_dates = [d.strftime("%Y-%m-%d") for d in future_idx]
            cloud_a_future = _si(df["senkou_a_raw"].tail(_ich_disp))
            cloud_b_future = _si(df["senkou_b_raw"].tail(_ich_disp))
        except Exception:
            pass

        pct5 = round((price / int(df.iloc[-6]["C"]) - 1) * 100, 2) if n >= 6 else 0.0
        pct20 = round((price / int(df.iloc[-21]["C"]) - 1) * 100, 2) if n >= 21 else 0.0

        price_52w, pct52 = None, None
        try:
            _back = min(n - 1, 252)
            if _back >= 20:
                price_52w = int(df.iloc[-(_back + 1)]["C"])
                if price_52w > 0:
                    pct52 = round((price / price_52w - 1) * 100, 1)
        except Exception:
            pass

        bb_squeeze = 0
        try:
            if n >= 40:
                _std20 = df["C"].rolling(20).std()
                _width = (_std20 * 4) / df["ma20"]
                _w = _width.dropna().tail(60)
                if len(_w) >= 20 and float(_w.iloc[-1]) <= float(_w.quantile(0.2)):
                    bb_squeeze = 1
        except Exception:
            pass

        # 🚨 [v106] 상장폐지 위험 경고용 — 가장 최근 거래일이 오늘로부터 얼마나 지났는지
        #    (오래됐으면 거래정지 가능성), 52주 최고가 대비 낙폭(장기간 폭락 여부).
        last_trade_date = df.index[-1].strftime("%Y-%m-%d")
        days_since_last_trade = (datetime.now().date() - df.index[-1].date()).days
        drawdown_52w = round((price / h52 - 1) * 100, 1) if h52 else 0.0

        return {
            "price": price, "prev": int(prev["C"]), "day_pct": dpct,
            "volume": int(lat["V"]), "vol_ratio": vr,
            "pos52": pos52, "ma20_diff": ma20d, "rsi": rsi, "ma_align": align,
            "tech_score": tech_score, "is_ipo": is_ipo, "data_days": n,
            "bb_squeeze": bb_squeeze, "price_52w": price_52w, "pct52": pct52,
            "high_52w": h52, "low_52w": l52, "drawdown_52w": drawdown_52w,
            "last_trade_date": last_trade_date, "days_since_last_trade": days_since_last_trade,
            "pct5": pct5, "pct20": pct20,
            "theory_text": "<br><br>".join(theory),
            "vp": vp_result,
            "chart": {
                "dates": [d.strftime("%Y-%m-%d") for d in cd.index],
                "open": _si(cd["O"]), "high": _si(cd["H"]), "low": _si(cd["L"]), "close": _si(cd["C"]),
                "volume": _si(cd["V"]), "ma5": _si(cd["ma5"]), "ma20": _si(cd["ma20"]), "ma60": _si(cd["ma60"]),
                "upper": _si(cd["upper"]), "lower": _si(cd["lower"]),
                # 🐛 [v113] 일목균형표 — 전환선·기준선은 실제 거래일(dates)과 같은 길이,
                # 구름(선행스팬 A/B)은 26일 미래까지 투영되므로 cloud_dates가 더 길다.
                "tenkan": _si(cd["tenkan"]), "kijun": _si(cd["kijun"]),
                "cloud_dates": [d.strftime("%Y-%m-%d") for d in cd.index] + cloud_future_dates,
                # 과거 구간은 26일 전 계산값을 오늘 날짜 위치에 표시(선행스팬 정의상 "이미
                # 지나간 26일 전 계산 결과"이므로 senkou_*_disp, 즉 shift(26) 버전을 사용),
                # 미래 구간(cloud_*_future)은 방금 계산한 원본 최근 26개 값을 그대로 이어붙인다.
                "senkou_a": _si(cd["senkou_a_disp"]) + cloud_a_future,
                "senkou_b": _si(cd["senkou_b_disp"]) + cloud_b_future,
            },
        }
    except Exception as e:
        print(f"[가격데이터] 오류: {e}")
        return None


# ══════════════════════════════════════════════════════════════
# 🚨 [v107] 상장폐지 위험종목 경고 — 네이버 증권 PC 개편 대응 재설계
# KRX 로그인·DART API 키가 없어 공식 감사의견·자본잠식 데이터는 조회할 수 없으므로,
# (1) 네이버 모바일 API의 거래상태 필드(tradableStatus 등 — 2026-09-11 PC 개편과
#     무관한 안정적 경로)와 (2) 가격/시가총액 데이터로 판단 가능한 정황(거래정지
#     추정·장기폭락·동전주·관리종목 시총기준 미달)을 근거로 참고용 경고를 만든다.
# 확정적 판정이 아니라 "확인이 필요하다"는 안내이므로, 화면·프롬프트 모두에 그 취지를 명시한다.
# ══════════════════════════════════════════════════════════════
def _naver_trading_status_flags(basic_data):
    """💡 [v107] 네이버 모바일 API의 구조화된 거래상태 필드를 확인한다. 예전 버전은
       페이지에 적힌 '관리종목' 등 문구를 직접 찾았지만, 그 페이지 자체가 개편으로
       사라져서 더는 쓸 수 없다 — 대신 tradableStatus/tradableStatusCode 필드로
       "거래 가능 상태가 아님"을 감지한다. 이 필드가 정확히 어떤 값일 때 어떤 사유인지는
       공식 문서가 없어 완전히 확정할 수는 없으므로, 신호가 있으면 '이상 신호'로만
       보고하고 사용자에게 직접 확인을 권고한다(과거처럼 '공식 경고 문구'라고 단정하지 않음)."""
    found = []
    if not basic_data:
        return found
    try:
        status = (basic_data.get("tradableStatus") or "").lower()
        code = (basic_data.get("tradableStatusCode") or "").lower()
        if status and status != "tradable":
            found.append(f"거래상태: {basic_data.get('tradableStatus')}")
        elif code and code != "ok":
            found.append(f"거래상태 코드: {basic_data.get('tradableStatusCode')}")
    except Exception:
        pass
    return found


def check_delisting_risk(price_d, risk_badges, cap_eok=None):
    """규칙 기반 위험도 판정 — 'danger'(거래상태 이상 신호) > 'caution'(가격·시총 데이터상
       의심 정황) > 'none'. 각 판정에 대한 구체적 근거(reasons)도 함께 반환한다.
       💡 [v107] cap_eok(시가총액·억원) 인자 추가 — 관리종목 지정의 실제 기준 중 하나인
       시가총액 미달(코스닥 40억/코스피 50억 등 최저 기준)을 새로 확인한다. 이 기준은
       시장·업종에 따라 세부 조건이 다양해 여기서는 '뚜렷하게 낮은' 경우만 보수적으로 표시."""
    reasons = []
    level = "none"

    if risk_badges:
        level = "danger"
        reasons.append(f"네이버 API에서 다음 거래상태 이상 신호가 감지되었습니다: {', '.join(risk_badges)} — 정상 거래 종목이 아닐 가능성이 있습니다.")

    p = price_d or {}
    days_stale = p.get("days_since_last_trade")
    if isinstance(days_stale, int) and days_stale >= 10:
        if level == "none":
            level = "caution"
        reasons.append(f"가장 최근 거래일이 {p.get('last_trade_date', 'N/A')}로, 오늘로부터 {days_stale}일이 지났습니다 — 거래정지 상태일 가능성이 있습니다.")

    drawdown = p.get("drawdown_52w")
    price_now = p.get("price")
    if isinstance(drawdown, (int, float)) and drawdown <= -80 and isinstance(price_now, int) and price_now < 2000:
        if level == "none":
            level = "caution"
        reasons.append(f"52주 최고가 대비 {abs(drawdown)}% 폭락한 상태이며 현재가도 {price_now:,}원으로 매우 낮습니다 — 부실 위험이 있는 종목일 수 있습니다.")

    if isinstance(price_now, int) and 0 < price_now < 1000:
        if level == "none":
            level = "caution"
        reasons.append(f"현재가가 {price_now:,}원으로 이른바 '동전주' 구간(1,000원 미만)입니다 — 관리종목 지정 사유 중 하나인 저가주 기준에 해당할 수 있습니다.")

    if isinstance(cap_eok, (int, float)) and cap_eok < 40:
        if level == "none":
            level = "caution"
        reasons.append(f"시가총액이 약 {cap_eok:,.0f}억원으로 관리종목 지정의 시가총액 기준선(대략 40억원 내외, 시장·조건별 상이) 부근이거나 미달일 수 있습니다.")

    return {"level": level, "reasons": reasons}

# ══════════════════════════════════════════════════════════════
# 기업개요 + 재무지표 — 네이버 모바일 증권 API(핵심 지표) + FnGuide(매출구성) 공개
# 데이터 사용(로그인 불필요)
# ══════════════════════════════════════════════════════════════
def get_company_details_and_fundamentals(ticker: str):
    """⚡ [v119] 기존 호출부 호환용 — 필요한 조각을 병렬로 받아 _build_details로 조립한다."""
    _, basic, integ, rev, extra = _fetch_all_parallel(ticker, need_price=False)
    return _build_details(basic, integ, rev, extra)


def _build_details(basic, integ, revenue, extra=None):
    """💡 [v107] 2026-09-11 네이버 증권 PC 개편 대응 — finance.naver.com/item/main.naver,
       coinfo.naver HTML 크롤링이 Next.js 리뉴얼로 완전히 무력화되어(서버가 내려주는
       최초 HTML에 실제 데이터가 없음, 실측 확인) 개편과 무관한 모바일 증권 API로 교체.
       FnGuide(comp.fnguide.com)는 이번 개편과 무관한 별개 도메인이라 그대로 유지.
       💡 부가가치: 이 API는 예전 페이지에는 없던 동일업종 PEER 비교·애널리스트
       컨센서스(목표주가·투자의견)까지 제공해, 공개판인데도 기능이 더 늘었다."""
    details = {
        "overview": "", "overview_source": "", "market_cap": "N/A", "shares": "N/A", "cap_eok": None,
        "market_type": "—", "sector": "—", "revenue_breakdown": "",
        "risk_badges": [], "peers": [], "consensus": None,
    }
    fundamentals = {"PER": None, "PBR": None, "EPS": None, "BPS": None, "DIV": None, "sector_PER": None}

    def _num(v):
        if not v or v in ("-", "N/A"):
            return None
        try:
            return float(str(v).replace(",", "").replace("배", "").replace("원", "").replace("%", "").strip())
        except Exception:
            return None

    if basic:
        details["risk_badges"] = _naver_trading_status_flags(basic)
        ext = (basic.get("stockExchangeType") or {}).get("nameEng", "").upper()
        if ext in ("KOSPI", "KOSDAQ", "KONEX"):
            details["market_type"] = ext

    researches = []
    if integ:
        try:
            info_map = {x.get("code"): x.get("value") for x in (integ.get("totalInfos") or [])}
            cap_eok = _parse_cap_eok(info_map.get("marketValue"))
            details["cap_eok"] = cap_eok
            if cap_eok is not None:
                details["market_cap"] = f"{cap_eok:,}억원"
            fundamentals["PER"] = _num(info_map.get("per"))
            fundamentals["PBR"] = _num(info_map.get("pbr"))
            fundamentals["EPS"] = _num(info_map.get("eps"))
            fundamentals["BPS"] = _num(info_map.get("bps"))
            fundamentals["DIV"] = _num(info_map.get("dividendYieldRatio"))

            # 💡 동일업종 PEER 비교 — 네이버 개편 이전 버전에는 없던 신규 기능.
            # 주의: 이 API의 industryCompareInfo 항목에는 PER/PBR/시총 필드가 없어
            # (확인된 필드는 종목명·현재가·등락률뿐) 확실하지 않은 수치를 지어내지
            # 않도록 가격·등락률만 표시한다.
            peers = []
            for p in (integ.get("industryCompareInfo") or [])[:6]:
                peers.append({
                    "ticker": p.get("itemCode", ""), "name": p.get("stockName", ""),
                    "price": _num(p.get("closePrice")),
                    "day_pct": _num(p.get("fluctuationsRatio")),
                })
            details["peers"] = peers

            # 💡 애널리스트 컨센서스(목표주가·투자의견) — 이 역시 신규 제공 정보.
            cons = integ.get("consensusInfo")
            if cons and (cons.get("priceTargetMean") or cons.get("recommMean")):
                details["consensus"] = {
                    "target_price": _num(cons.get("priceTargetMean")),
                    "recomm_mean": _num(cons.get("recommMean")),
                    "date": cons.get("createDate"),
                }

            # 🐛 [v110] "기업개요가 이상한 텍스트 나열로 보임" 신고 대응 — 아래 ②③단계는
            # 정상 유지. ①단계였던 레거시 엔드포인트(getOverallInfo.nhn) 시도는 제거했다.
            # 실제로 호출해보니 이 API는 회사 소개 문단이 아니라 "전일가·시가·고가·거래량·
            # 시총·PER·EPS·PBR…" 같은 미니 시세 위젯 데이터를 순서대로 나열한 HTML이었다
            # (스크린샷으로 실측 확인) — 이미 basic/integration으로 얻고 있는 수치들을
            # 텍스트로 흩뿌린 것뿐, 사업 설명이 아니라서 "네이버 제공 기업개요"로 보여주면
            # 오히려 혼란스러웠다. 근거 없이 "혹시 될 수도"인 시도는 걷어내고, 실제로
            # 검증된 두 경로(증권사 리포트 제목 → AI 분석 추출)만 남긴다.
            researches = integ.get("researches") or []
        except Exception as e:
            researches = []
            print(f"[기업개요] 네이버모바일 파싱 오류(무시): {e}")

    if researches:
        titles = "; ".join(f"[{r.get('bnm','')}] {r.get('tit','')}" for r in researches[:3] if r.get("tit"))
        if titles:
            details["overview"] = f"(최근 증권사 리포트 제목 — 개요 문단은 제공되지 않아 참고용으로 대신 표시합니다)\n{titles}"
            details["overview_source"] = "naver_reports"

    if not details["overview"]:
        details["overview"] = "네이버에서 기업개요를 가져오지 못했습니다 — AI 분석을 실행하면 [1. 기업 소개] 섹션이 자동으로 이 자리를 채웁니다."
        details["overview_source"] = "ai_pending"

    extra = extra or {}
    details["financials"] = {"annual": extra.get("fin_annual"), "quarter": extra.get("fin_quarter")}  # 📑 [v121]
    details["news"] = extra.get("news") or []                                                         # 📰 [v121]
    details["partial"] = bool(extra.get("partial"))          # ⚡ [v122] 네이버 불안정으로 일부 정보 생략
    details["price_source"] = extra.get("price_source") or ""
    if revenue:
        details["revenue_breakdown"] = revenue  # ⚡ [v119] FnGuide 조회는 _fnguide_revenue로 분리(하루 캐시)

    return details, fundamentals


# ══════════════════════════════════════════════════════════════
# AI 프롬프트 생성 — 실제 AI 호출은 하지 않는다("수동 모드").
# 사용자가 복사해서 자신의 AI 챗봇에 붙여넣도록 텍스트만 만들어 준다.
# 💡 [v102] "AI 분석 수준이 너무 낮다 — 원본과 비슷하게" — 원본 앱의 실제 종목분석
#    프롬프트(전문 애널리스트 리포트, 섹션별 구성·서술 규칙·매물대 원단위 인용·
#    구체적 매수/매도 가격대 요구 등)를 그대로 모델로 삼아 대폭 강화했다.
#    다만 이 공개판은 DART 다년도 재무·수급(외국인/기관)·뉴스/공시 데이터가 없으므로
#    (KRX 로그인·DART API 키가 필요해 공개판에서 의도적으로 제외) 그 부분을 지어내지
#    않도록 프롬프트에서 명시적으로 "데이터 없음"을 밝히고 한계를 안내하게 했다 —
#    분량만 늘리는 게 아니라, 있는 데이터를 원본 수준으로 깊이 있게 쓰도록 지시문
#    자체를 강화하는 데 초점을 맞췄다.
# ══════════════════════════════════════════════════════════════
def build_ai_prompt(ticker, name, market, price_d, fundamentals, details, delisting_risk=None):
    p = price_d or {}
    f = fundamentals or {}
    d = details or {}
    vp = p.get("vp") or {}
    current_year = datetime.now().year

    price_str = f"{p.get('price', 0):,}" if isinstance(p.get("price"), (int, float)) else "N/A"
    h52 = p.get("high_52w"); l52 = p.get("low_52w")
    range52_str = f"{l52:,}원 ~ {h52:,}원" if (h52 and l52) else "데이터 부족"
    price52_str = f"{p.get('price_52w'):,}원" if p.get("price_52w") else "N/A"

    risk_warning_section = ""
    dr = delisting_risk or {}
    if dr.get("level") in ("danger", "caution"):
        label = "🚨 상장폐지 위험 경고 (공식 경고 문구 발견)" if dr.get("level") == "danger" else "⚠️ 상장폐지 위험 주의 (정황상 의심)"
        reason_lines = "\n".join(f"- {r}" for r in dr.get("reasons", []))
        risk_warning_section = f"""

[{label}]
{reason_lines}
이 종목은 위와 같은 이유로 상장폐지·거래정지 위험 신호가 감지되었습니다. 반드시 [6. 리스크 및 유의사항]
섹션 맨 앞에서 이 내용을 가장 먼저, 구체적으로 언급하고, 투자자에게 KRX·DART 공시를 통한 직접 확인을
강하게 권고하세요."""

    vp_section = ""
    poc_str = val_str = vah_str = "N/A"
    if vp and vp.get("poc"):
        poc_str = f"{vp.get('poc', 0):,}원"
        val_str = f"{vp.get('val', 0):,}원"
        vah_str = f"{vp.get('vah', 0):,}원"
        vp_section = f"""
[매물대(Volume Profile) 데이터 — 최근 60거래일]
- POC(최대 매물 기준가): {poc_str}
- VAL(가치 영역 하단·핵심 지지선): {val_str}
- VAH(가치 영역 상단·핵심 저항선): {vah_str}
- 현재가 대비 POC 위치: {vp.get('poc_diff_str', 'N/A')}
- 현재가 위치 판정: {vp.get('va_pos', 'N/A')}"""
    else:
        vp_section = "\n[매물대(Volume Profile) 데이터]\n데이터 부족으로 산출되지 않음(상장 기간이 짧거나 가격 변동폭이 매우 작은 경우)."

    fin_lines = []
    if f.get("PER"): fin_lines.append(f"- PER: {f.get('PER')}배" + (f" (업종 평균 PER: {f.get('sector_PER')}배)" if f.get("sector_PER") else ""))
    if f.get("PBR"): fin_lines.append(f"- PBR: {f.get('PBR')}배")
    if f.get("EPS"): fin_lines.append(f"- EPS(주당순이익): {f.get('EPS')}원")
    if f.get("BPS"): fin_lines.append(f"- BPS(주당순자산): {f.get('BPS')}원")
    if f.get("DIV"): fin_lines.append(f"- 배당수익률: {f.get('DIV')}%")
    fin_summary_text = "\n".join(fin_lines) if fin_lines else "- 밸류에이션 지표 조회 실패(비상장·거래정지 등 가능성)"

    # 💡 [v107] 동일업종 PEER 비교 — 네이버 PC 페이지에는 없던, 새 데이터 소스 덕에
    # 추가된 섹션. 가격·등락률만 확실히 확인되므로 그 범위 내에서만 서술하도록 안내.
    peers = d.get("peers") or []
    if peers:
        peer_lines = "\n".join(
            f"- {p.get('name')}({p.get('ticker')}): 현재가 {p.get('price'):,.0f}원, 등락 {p.get('day_pct'):+.2f}%"
            if p.get("price") is not None else f"- {p.get('name')}({p.get('ticker')})"
            for p in peers
        )
        peer_section = f"\n[동일업종 관련 종목 (참고용, PER/PBR 없이 가격·등락률만 제공됨)]\n{peer_lines}"
    else:
        peer_section = ""

    consensus = d.get("consensus")
    if consensus and consensus.get("target_price"):
        cons_txt = f"목표주가 평균 {consensus['target_price']:,.0f}원"
        if consensus.get("recomm_mean") is not None:
            cons_txt += f", 투자의견 점수 {consensus['recomm_mean']} (1=강력매수~5=매도 척도, 낮을수록 긍정적)"
        if consensus.get("date"):
            cons_txt += f" ({consensus['date']} 기준)"
        consensus_section = f"\n[증권사 애널리스트 컨센서스]\n- {cons_txt}\n※ 이는 증권사들의 평균 전망치이며 실제 주가와 다를 수 있습니다. 목표주가와 현재가를 비교해 괴리율을 언급하되, 이 수치 자체를 매수/매도 근거로 단정하지 마세요."
    else:
        consensus_section = ""

    # 📑 [v121] 재무제표 추이(연간·분기) — 표 형태 텍스트
    def _fin_text(fin, label):
        if not fin or not fin.get("periods"):
            return f"\n[{label}]\n데이터 없음"
        heads = [pp["title"] + ("(E)" if pp.get("estimate") else "") for pp in fin["periods"]]
        lines = [f"\n[{label}] (금액 억원·비율 %·주당 원, (E)=증권사 추정치)", "- 기간: " + " | ".join(heads)]
        for row in fin["rows"]:
            lines.append(f"- {row['name']}: " + " | ".join("-" if v is None else f"{v:,.2f}".rstrip("0").rstrip(".") for v in row["values"]))
        return "\n".join(lines)
    fins = d.get("financials") or {}
    fin_section = _fin_text(fins.get("annual"), "재무제표 추이 — 연간") + _fin_text(fins.get("quarter"), "재무제표 추이 — 분기")

    # 📰 [v121] 최근 14일 뉴스 헤드라인(제목만 — 본문은 포함하지 않음)
    news = d.get("news") or []
    if news:
        news_section = f"\n[최근 {NEWS_DAYS}일 관련 뉴스 헤드라인 — 제목만 제공, 최신순]\n" + "\n".join(
            f"- {n['date']} {n['press']}: {n['title']}" + (f" (관련 기사 {n['related']}건 더)" if n.get("related") else "")
            for n in news[:NEWS_LIMIT])
    else:
        news_section = f"\n[최근 {NEWS_DAYS}일 관련 뉴스]\n최근 {NEWS_DAYS}일 이내 관련 뉴스 없음"

    overview_text = d.get("overview") or "기업 개요 정보를 가져오지 못했습니다."
    rev_breakdown = d.get("revenue_breakdown") or "정보 없음"

    prompt = f"""주식 종목 [{name}({ticker})]에 대한 전문 투자 분석 리포트를 작성하세요.

[현재 시점 — 반드시 준수]
- 오늘은 {current_year}년입니다.
- 아래 밸류에이션 수치(PER·PBR·EPS·BPS·배당수익률)는 조회 시점 기준 스냅샷입니다. "예상", "전망" 같은 표현을 쓰지 말고 "현재 기준"임을 명확히 하세요.
- 미래 전망이 필요한 경우 반드시 "~로 보인다", "~할 가능성이 있다" 등 헤지 표현을 사용하고, 단정적으로 서술하지 마세요.

[종목 기본 정보]
- 종목명: {name} ({ticker})
- 시장구분: {market} | 업종: {d.get('sector', 'N/A')}
- 시가총액: {d.get('market_cap', 'N/A')}
- 주요 매출 구성: {rev_breakdown}

[기업 개요 — 네이버금융 발췌]
{overview_text}

[밸류에이션 지표 — 조회 시점 스냅샷]
{fin_summary_text}
{peer_section}
{consensus_section}

[가격/기술적 데이터]
- 현재가: {price_str}원 (전일대비 {p.get('day_pct', 0)}%)
- 이동평균 배열: {p.get('ma_align', 'N/A')} (20일선 대비 이격도 {p.get('ma20_diff', 0)}%)
- RSI(14일): {p.get('rsi', 'N/A')}
- 거래량 배수(20일 평균 대비): {p.get('vol_ratio', 'N/A')}배
- 52주 최고/최저: {range52_str}
- 52주 위치: {p.get('pos52', 'N/A')}% (0=52주 최저, 100=52주 최고)
- 52주 전 대비 등락률: {p.get('pct52', 'N/A')}% (52주 전 주가 {price52_str})
- 최근 5일/20일 등락률: {p.get('pct5', 0)}% / {p.get('pct20', 0)}%
- 볼린저밴드 스퀴즈(변동성 압축) 여부: {'예 — 방향성 돌파 전조 가능' if p.get('bb_squeeze') else '아니오'}
{vp_section}
{fin_section}
{news_section}
{risk_warning_section}

[이 리포트에 포함되지 않은 데이터 — 반드시 명시할 것]
- 외국인·기관 수급(순매수/순매도) 데이터 없음
- 공시(DART) 원문과 뉴스 본문은 없음(뉴스는 최근 {NEWS_DAYS}일 제목만 제공)
- 위 항목들은 KRX 로그인 또는 DART API 키가 필요해 이 공개용 프로그램에는 포함되지 않았습니다.

[작성 지침 — 반드시 지킬 것]
1. 반드시 아래 순서대로, 각 섹션 제목은 [섹션명] 형식을 정확히 사용하세요.
2. 과장된 수식어 없이 객관적·냉철한 어조로 작성하세요. 확정되지 않은 것을 단정하지 마세요.
3. 항목별로 '•' 기호를 사용하고, 섹션 사이에 줄바꿈을 두세요.
4. <br> 같은 HTML 태그는 절대 사용하지 마세요. 마크다운(**굵게**, - 목록)만 사용하세요.
5. 매물대 데이터가 있는 경우, POC·VAH·VAL 수치를 원 단위로 정확히 인용하고 주식 초보자도 이해할 수 있도록 쉬운 말로 풀어 설명하세요.
6. 위에 명시한 "포함되지 않은 데이터"(수급·공시 원문·뉴스 본문)는 절대 있는 것처럼 지어내지 말고, [리스크 및 유의사항]에서 "이 리포트는 수급 데이터와 공시 원문을 포함하지 않으며 뉴스는 제목만 참고했으므로, 투자 결정 전 별도 확인이 필요하다"고 명시하세요.
6-1. 재무 수치는 위 [재무제표 추이] 표의 숫자만 인용하세요. (E)가 붙은 값은 반드시 "증권사 추정치"라고 밝히고 확정 실적처럼 쓰지 마세요.
6-2. 뉴스는 제목만 주어졌으므로 제목에서 확인되는 사실만 언급하고, 제목에 없는 내용(수치·원인·결과)을 추측해 덧붙이지 마세요.
7. 제공되지 않은 수치는 추측해서 채우지 말고 "데이터 없음"이라고 쓰세요.
8. 마지막 줄에 블로그용 해시태그를 10개 내외로 작성하세요.

[리포트 구성 — 순서대로 작성]
[1. 기업 소개 및 사업 개요]
- 회사의 주력 사업과 핵심 제품/서비스를 위 기업 개요를 바탕으로 구체적으로 설명하세요.
- 주요 매출 구성이 제공된 경우 사업부별 비중을 해석하세요.

[2. 밸류에이션 분석]
- PER·PBR·배당수익률을 업종 평균(제공된 경우)과 비교해 현재 밸류에이션 수준(고평가/저평가/적정)을 평가하세요.
- EPS·BPS가 있다면 이를 근거로 한 판단도 함께 제시하세요.
- [동일업종 관련 종목]이 제공된 경우, 이 종목의 오늘 등락률이 같은 업종 종목들과 비슷한 흐름인지 유독 다른지 비교해 언급하세요(단, 이 목록엔 PER/PBR이 없으므로 가격·등락률 비교로 한정).
- [증권사 애널리스트 컨센서스]가 제공된 경우, 목표주가 대비 현재가 괴리율(%)을 계산해 언급하되, 이는 증권사 평균 전망일 뿐 확정이 아니라는 점을 함께 명시하세요.

[3. 실적·재무 분석]
- 최근 3년 매출액·영업이익·당기순이익의 증감 추세(성장/정체/감소)와 전년 대비 증감률을 숫자로 짚으세요.
- 영업이익률·순이익률·ROE로 수익성을, 부채비율·당좌비율로 재무 안정성을 평가하세요(초보자도 알 수 있게 기준을 함께 설명).
- 최근 분기 흐름이 연간 추세와 같은 방향인지, 추정치(E)가 있다면 시장이 기대하는 방향이 무엇인지 설명하세요.
- 주당배당금 추이가 있다면 배당 성향을 간단히 언급하세요. 재무 데이터가 없으면 "재무 데이터 없음"으로 처리하세요.

[4. 최근 뉴스·이슈 점검]
- 최근 {NEWS_DAYS}일 헤드라인에서 반복되는 주제(실적·수주·규제·업황 등)를 2~4개로 묶어 정리하고, 주가에 긍정/부정 중 어느 쪽 재료로 해석될 수 있는지 조심스럽게 서술하세요.
- 뉴스가 없으면 "최근 2주간 눈에 띄는 뉴스 없음"으로 간단히 처리하세요.

[5. 기술적 분석 심층]
- 이동평균 배열·RSI·거래량 배수·52주 위치·이격도를 종합해 현재 추세 국면(상승/하락/횡보, 과열/침체)을 판단하세요.
- 볼린저밴드 스퀴즈가 감지된 경우, 방향성 돌파 가능성과 그 방향을 가늠할 근거가 있는지 짚어주세요.

[6. 매물대 기술적 분석]
- POC(최대 매물 기준가)·VAL(핵심 지지선)·VAH(핵심 저항선)의 의미와 현재가가 그 사이 어디에 위치하는지 설명하세요.
- 초보 투자자도 이해할 수 있도록 어려운 용어는 괄호 안에 쉬운 말로 풀어 쓰세요.
- 매물대 데이터가 없다면 이 섹션은 "데이터 부족으로 매물대 분석 불가"로 간단히 처리하세요.

[7. 투자 전략 제안]
- 매물대 수치가 있다면 그 가격대를 근거로 구체적인 관심 진입 가격대와 참고 손절/익절 기준을 원 단위로 제안하세요. (예: "VAL({val_str}) 부근에서 분할 매수를 고려할 수 있으며...")
- 단기(1~2주)와 중기(1~3개월) 관점을 구분해서 서술하세요.
- 이것이 투자 추천이 아니라 데이터에 근거한 참고 의견임을 분명히 하세요.

[8. 리스크 및 유의사항]
- RSI 과열·이격도 과다 등 기술적 리스크와, 재무(이익 감소·부채비율 상승 등)·뉴스에서 확인되는 리스크를 함께 짚으세요.
- 반드시 위 6번 지침대로 수급·공시 원문 미포함, 뉴스는 제목만 참고했음을 명시하고, 투자 결정 전 확인을 권고하세요.
- 원금 손실 가능성과 투자 판단·책임이 투자자 본인에게 있음을 명시하세요.

[9. 해시태그]
#{name} #{ticker} #주식분석 #기술적분석 #매물대분석 #주린이
"""
    return prompt


# ══════════════════════════════════════════════════════════════
# 📝 [v118] 로드맵 '초기 보급' 5순위 — 블로그용 글 자동 생성
# ──────────────────────────────────────────────────────────────
# build_ai_prompt()와 헷갈리기 쉬운데 목적이 다르다: 저건 "AI에게 분석을 시키는 지시문"이고
# 이건 "사람이 그대로 복사해서 블로그에 붙여넣는 완성된 글"이다. AI 호출이 전혀 없으므로
# 0원·즉시 생성이며, /api/blog-export가 이미 가진 분석 데이터(_resolve_analysis_source)로
# 만들어 호출한다(별도 네이버 재조회 없음).
# ══════════════════════════════════════════════════════════════
def build_blog_draft(ticker, name, market, price_d, fundamentals, details, delisting_risk=None, site_url=""):
    p = price_d or {}
    f = fundamentals or {}
    d = details or {}
    vp = p.get("vp") or {}
    today_str = datetime.now().strftime("%Y.%m.%d")
    price_str = f"{p.get('price', 0):,}" if isinstance(p.get("price"), (int, float)) else "N/A"

    lines = [f"【{name}({ticker}) 주가 분석 — {today_str} 기준】", ""]
    lines.append(f"시장: {market} | 현재가: {price_str}원 (전일대비 {p.get('day_pct', 0)}%)")

    fin_bits = []
    if f.get("PER"): fin_bits.append(f"PER {f.get('PER')}배")
    if f.get("PBR"): fin_bits.append(f"PBR {f.get('PBR')}배")
    if f.get("DIV"): fin_bits.append(f"배당수익률 {f.get('DIV')}%")
    if fin_bits:
        lines.append("💰 밸류에이션: " + " · ".join(fin_bits))

    tech_bits = []
    if p.get("ma_align"): tech_bits.append(f"이동평균 {p.get('ma_align')}")
    if p.get("rsi") is not None: tech_bits.append(f"RSI {p.get('rsi')}")
    if p.get("pos52") is not None: tech_bits.append(f"52주 위치 {p.get('pos52')}%")
    if tech_bits:
        lines.append("📊 기술적 지표: " + " · ".join(tech_bits))

    fa = (d.get("financials") or {}).get("annual") or {}
    try:
        pers = fa.get("periods") or []
        act = [i for i, pp in enumerate(pers) if not pp.get("estimate")]
        rows_ = {r["name"]: r["values"] for r in (fa.get("rows") or [])}
        if act and rows_.get("매출액"):
            i = act[-1]
            def _jo(v):
                return "-" if v is None else (f"{v/10000:,.1f}조원" if abs(v) >= 10000 else f"{v:,.0f}억원")
            txt = f"📑 {pers[i]['title']} 실적: 매출 {_jo(rows_['매출액'][i])}"
            if rows_.get("영업이익"):
                txt += f" · 영업이익 {_jo(rows_['영업이익'][i])}"
            if len(act) >= 2 and rows_["매출액"][act[-2]]:
                prev = rows_["매출액"][act[-2]]
                if prev and rows_["매출액"][i] is not None:
                    txt += f" (매출 전년 대비 {(rows_['매출액'][i]/prev-1)*100:+.1f}%)"
            lines.append(txt)
    except Exception:
        pass

    if vp and vp.get("poc"):
        lines.append(
            f"🎯 매물대: POC {vp.get('poc', 0):,.0f}원 · 지지선(VAL) {vp.get('val', 0):,.0f}원 "
            f"· 저항선(VAH) {vp.get('vah', 0):,.0f}원")

    overview = d.get("overview")
    if overview and "가져오지 못했습니다" not in overview:
        lines.append("")
        lines.append("🏢 기업개요: " + overview[:200] + ("..." if len(overview) > 200 else ""))

    dr = delisting_risk or {}
    if dr.get("level") in ("danger", "caution"):
        lines.append("")
        lines.append("🚨 주의: 상장폐지·거래정지 관련 위험 신호가 감지된 종목입니다. "
                      "투자 전 KRX·DART 공시를 꼭 확인하세요.")

    lines.append("")
    lines.append("※ 이 글은 공개 데이터를 근거로 한 개인적인 기술적 분석 기록이며 투자 권유가 아닙니다. "
                  "투자 판단과 그 책임은 본인에게 있습니다.")
    if site_url:
        lines.append("")
        lines.append(f"👉 이 종목 무료로 직접 분석해보기: {site_url}/?t={ticker}")
    if KAKAO_OPENCHAT_URL:
        lines.append(f"💬 함께 이야기 나누기: {KAKAO_OPENCHAT_URL}")
    lines.append("")
    lines.append(f"#{name} #{ticker} #주식분석 #{market} #주린이")
    return "\n".join(lines)


# ══════════════════════════════════════════════════════════════
# Flask 라우트
# ══════════════════════════════════════════════════════════════
@app.route("/")
def index():
    return render_template_string(
        HTML_TEMPLATE, app_version=APP_VERSION, slogan=APP_SLOGAN,
        kakao_url=KAKAO_OPENCHAT_URL or None,
        demo_ticker=DEMO_TICKER, demo_name=DEMO_TICKER_NAME,
        site_url=_public_site_url(),
        site_label=(PUBLIC_SITE_URL or _public_site_url() or "").replace("https://", "").replace("http://", "").rstrip("/"),
        brand_url=(PUBLIC_SITE_URL or _public_site_url() or "").rstrip("/"),
        blog_url=CREATOR_BLOG_URL,
        ad_client=ADSENSE_CLIENT, ad_slots=ADSENSE_SLOTS, ad_hints=ADSENSE_SLOT_HINTS,
        ad_preview=(request.args.get("adpreview") == "1"),
    )


@app.route("/help")
def help_page():
    """💡 [v113] 증권용어 도움말 페이지. HELP_CONTENT_ASOF(도움말이 마지막으로 맞춰
       작성된 앱 버전)와 실제 APP_VERSION_HARDCODED(현재 앱의 진짜 버전)가 다르면
       — 즉 화면은 업데이트됐는데 도움말 갱신을 깜빡했다면 — 자동으로 경고 배너를
       띄운다. 파일 상단의 HELP_CONTENT_ASOF 주석에 갱신 규칙이 적혀 있다."""
    stale = HELP_CONTENT_ASOF != APP_VERSION_HARDCODED
    return render_template_string(HELP_HTML, app_version=APP_VERSION,
                                   asof=HELP_CONTENT_ASOF, stale=stale)


@app.route("/api/search")
def api_search():
    return jsonify(search_tickers(request.args.get("q", "")))


@app.route("/api/refresh-tickers", methods=["POST"])
def api_refresh_tickers():
    if not FDR_OK:
        return jsonify({"ok": False, "msg": "FinanceDataReader가 설치되어 있지 않습니다."})
    threading.Thread(target=lambda: build_ticker_cache(force=True), daemon=True).start()
    return jsonify({"ok": True, "msg": "종목 목록을 백그라운드에서 갱신 중입니다(약 10~20초 소요)."})


_INFLIGHT = {}
_INFLIGHT_LOCK = threading.Lock()


def _compute_analysis(ticker):
    """실제로 데이터를 불러와 분석 결과(dict)를 만든다. 실패하면 {"error": ...}."""
    name, market = get_ticker_info(ticker)
    price_d, basic, integ, rev, extra = _fetch_all_parallel(ticker)
    if not price_d:
        return {"error": f"주가 데이터를 가져오지 못했어요({ticker}). 네이버 응답이 늦거나 없는 종목코드일 수 있어요."}
    details, fundamentals = _build_details(basic, integ, rev, extra)

    # 🐛 [v1.1] 검색 캐시에 없는 종목도 분석되도록 실제 종목명을 채워 넣는다("자가 치유" 캐시).
    # ⚡ [v119] 이미 받아온 basic 응답에서 이름을 꺼내므로 네이버를 한 번 더 부르지 않는다.
    if not name:
        name, live_market = _name_from_basic(basic)
        market = market or live_market
        if name:
            try:
                db_save_tickers([(ticker, name, market or "—")])
            except Exception:
                pass
        else:
            name = ticker

    return {
        "ticker": ticker, "name": name, "market": market or "—",
        "price": price_d,
        "details": details, "fundamentals": fundamentals,
        "delisting_risk": check_delisting_risk(price_d, details.get("risk_badges") or [], details.get("cap_eok")),
        "as_of": _now_kst().strftime("%m/%d %H:%M"),
    }


def _get_analysis(ticker):
    """캐시에 있으면 즉시, 없으면 계산. 같은 종목을 여러 사람이 동시에 요청해도 실제 조회는
       한 번만 하고 나머지는 그 결과를 함께 기다린다(데모 버튼이 몰릴 때 대비).
       반환: (결과 dict, 캐시 적중 여부)."""
    key = ("analyze", ticker)
    hit = _cache_get(key)
    if hit is not None:
        return hit, True
    with _INFLIGHT_LOCK:
        fut = _INFLIGHT.get(ticker)
        owner = fut is None
        if owner:
            fut = Future()
            _INFLIGHT[ticker] = fut
    if not owner:
        return fut.result(timeout=40), True
    try:
        payload = _compute_analysis(ticker)
        if "error" not in payload:
            _cache_set(key, payload, _analysis_ttl())
            _cache_set(("last", ticker), payload, 3 * 86400)   # 🐛 [v120] 최근 성공 결과 3일 보관
        else:
            # 🐛 [v120] 네이버가 답하지 않을 때 빈 화면 대신 최근 성공 결과를 보여준다(기준 시각 표시).
            last = _cache_get(("last", ticker))
            if last:
                payload = dict(last, stale=True)
                print(f"[분석] {ticker}: 새로 가져오기 실패 → {last.get('as_of')} 기준 결과로 대체")
        fut.set_result(payload)
        return payload, False
    except Exception as e:
        fut.set_exception(e)
        raise
    finally:
        with _INFLIGHT_LOCK:
            _INFLIGHT.pop(ticker, None)


def _popular_tickers(n=4):
    """최근 기록 500건 중 많이 본 종목 상위 n개(미리 불러두기 대상)."""
    if not _ensure_history_table():
        return []
    try:
        conn = _history_conn()
        try:
            c = conn.cursor()
            c.execute("SELECT ticker FROM search_history ORDER BY id DESC LIMIT 500")
            return [t for t, _ in Counter(r[0] for r in c.fetchall()).most_common(n)]
        finally:
            conn.close()
    except Exception:
        return []


def _warm_cache_loop():
    """⚡ [v119] 데모 종목과 많이 보는 종목을 미리 불러 캐시에 넣어 둔다 — 첫 방문자가 데모
       버튼을 누르면 기다림 없이 결과가 뜨게 하기 위함. 데스크톱은 시작 시 한 번만,
       웹 배포는 캐시가 만료되기 직전마다 다시 채운다."""
    # 🐛 [v120] 서버가 막 켜졌을 때는 종목목록 갱신과 겹치지 않도록 잠시 기다리고, 한 번에
    # 몰아서 요청하지 않도록 종목 사이에 3초씩 쉰다(네이버에 한꺼번에 요청이 몰리지 않게).
    time.sleep(20 if _WEB_MODE else 3)
    while True:
        for t in dict.fromkeys([DEMO_TICKER] + (_popular_tickers(2) if _WEB_MODE else [])):
            try:
                payload = _compute_analysis(t)
                if "error" not in payload:
                    _cache_set(("analyze", t), payload, _analysis_ttl())
                    _cache_set(("last", t), payload, 3 * 86400)
            except Exception as e:
                print(f"[미리불러오기] {t} 실패(무시): {e}")
            time.sleep(3)
        if not _WEB_MODE:
            return
        time.sleep(max(90, _analysis_ttl() - 30))


@app.route("/api/analyze/<ticker>")
def api_analyze(ticker):
    if not FDR_OK:
        return jsonify({"error": "FinanceDataReader가 설치되어 있지 않습니다. "
                                  "pip install finance-datareader 후 다시 실행해 주세요."}), 400
    ticker = normalize_ticker(ticker)
    if not ticker:
        return jsonify({"error": "올바른 종목코드가 아닙니다."}), 400
    t0 = time.time()
    payload, cached = _get_analysis(ticker)
    if "error" in payload:
        return jsonify(payload), 400

    # 💡 [v117] 로드맵 1단계 — 이 종목을 봤다는 사실을 익명 uid로 기록한다.
    history_save(g.get("anon_uid"), ticker, payload.get("name"), payload.get("market") or "—")
    resp = jsonify(payload)
    resp.headers["X-Analyze-Cache"] = "hit" if cached else "miss"
    resp.headers["X-Analyze-Ms"] = str(int((time.time() - t0) * 1000))
    return resp


@app.route("/api/history")
def api_history():
    """💡 [v117] 로드맵 1단계 — 이 브라우저(anon_uid)가 최근 본 종목 목록. 첫 화면에
       "🕘 최근 본 종목" 칩으로 표시된다(같은 브라우저라면 새로고침·재방문해도 유지)."""
    return jsonify(history_recent(g.get("anon_uid")))


@app.before_request
def _redirect_to_public_site():
    """🔁 [v119] REDIRECT_TO_PUBLIC_SITE=True일 때 onrender.com으로 들어온 요청을 대표 주소로
       301 이동. 헬스체크(/healthz)는 Render 내부 점검이므로 제외한다."""
    if not (REDIRECT_TO_PUBLIC_SITE and _WEB_MODE and PUBLIC_SITE_URL) or request.path == "/healthz":
        return None
    host = (request.host or "").split(":")[0].lower()
    target = PUBLIC_SITE_URL.split("//", 1)[-1].split("/")[0].lower()
    if host.endswith(".onrender.com") and host != target:
        from flask import redirect
        qs = request.query_string.decode("utf-8", "ignore")
        return redirect(PUBLIC_SITE_URL.rstrip("/") + request.path + ("?" + qs if qs else ""), code=301)
    return None


@app.route("/ads.txt")
def ads_txt():
    """💰 [v119] 애드센스가 요구하는 ads.txt — ADSENSE_CLIENT를 채우면 자동으로 만들어진다."""
    if not ADSENSE_CLIENT:
        return "", 404
    pub = ADSENSE_CLIENT.replace("ca-", "")
    return (f"google.com, {pub}, DIRECT, f08c47fec0942fa0\n", 200,
            {"Content-Type": "text/plain; charset=utf-8"})


@app.route("/privacy")
def privacy_page():
    """🔒 [v119] 개인정보처리방침 — 애드센스 승인 조건이자, 익명 쿠키를 쓰는 서비스로서 공개해야 할 내용."""
    return render_template_string(PRIVACY_HTML, app_version=APP_VERSION, blog_url=CREATOR_BLOG_URL,
                                  site_label=(PUBLIC_SITE_URL or request.host_url).replace("https://", "").replace("http://", "").rstrip("/"))


@app.route("/healthz")
def healthz():
    """🩺 [v118] Render 헬스체크 전용 — 화면 템플릿을 그리지 않는 가장 가벼운 응답.
       render.yaml의 healthCheckPath가 이 주소를 본다(무중단 배포·장애 자동 감지용)."""
    return "ok", 200


@app.route("/api/history", methods=["DELETE"])
def api_history_clear():
    """🧹 [v121] 최근 본 종목 지우기(이 브라우저 것만)."""
    return jsonify({"ok": history_clear(g.get("anon_uid"))})


@app.route("/api/vote/<ticker>", methods=["GET", "POST"])
def api_vote(ticker):
    """💡 [v121] 매력도 체크 — GET: 집계, POST {"vote": "buy"|"watch"|"pass"|null}: 내 표 저장/취소."""
    ticker = normalize_ticker(ticker)
    if not ticker:
        return jsonify({"error": "올바른 종목코드가 아닙니다."}), 400
    uid = g.get("anon_uid")
    if request.method == "POST":
        body = request.get_json(silent=True) or {}
        vote = body.get("vote")
        if vote not in VOTE_CHOICES and vote is not None:
            return jsonify({"error": "잘못된 선택입니다."}), 400
        name = (str(body.get("name") or "")[:40]) or ticker
        if not vote_cast(uid, ticker, name, vote):
            return jsonify({"error": "저장하지 못했어요. 잠시 후 다시 시도해 주세요."}), 500
    return jsonify(vote_summary(ticker, uid))


@app.route("/api/vote-top")
def api_vote_top():
    """💡 [v121] 이번 주(7일) 매수 관심 TOP 5."""
    return jsonify(vote_top(7, 5))


@app.route("/api/diag")
def api_diag():
    """🩺 [v120] 진단 — 브라우저로 /api/diag 를 열면 서버에서 네이버·FnGuide 각 경로가 되는지,
       몇 초 걸리는지 한눈에 보여준다(문제가 생겼을 때 이 화면 내용을 그대로 알려주면 원인 파악 가능)."""
    ticker = normalize_ticker(request.args.get("t", DEMO_TICKER)) or DEMO_TICKER
    st = (datetime.now() - timedelta(days=420)).strftime("%Y-%m-%d")
    out = {"version": APP_VERSION_HARDCODED, "web_mode": _WEB_MODE, "db": "postgres" if _USE_PG else "sqlite",
           "history_ready": _history_ready, "cpu": os.cpu_count(), "cache_items": len(_CACHE),
           "fdr_ok": FDR_OK, "ticker": ticker, "now_kst": _now_kst().strftime("%Y-%m-%d %H:%M:%S"),
           "source_health": {k: {"recent_fails": len(v["fails"]), "skipped_for_sec": max(0, int(v["until"] - time.time()))}
                             for k, v in _SRC_HEALTH.items()},
           "last_price_source": dict(list(PRICE_LAST_SOURCE.items())[-10:]), "checks": []}
    checks = [(f"price:{n}", (lambda fn=fn: fn(ticker, st))) for n, fn in _PRICE_SOURCES] + [
        ("naver_basic", lambda: _naver_mobile_basic(ticker)),
        ("naver_integration", lambda: _naver_mobile_integration(ticker)),
        ("fnguide_revenue", lambda: _fnguide_revenue(ticker)),
    ]
    for name, fn in checks:
        t0 = time.time()
        try:
            v = fn()
            size = len(v) if hasattr(v, "__len__") else (1 if v else 0)
            out["checks"].append({"name": name, "ok": bool(v is not None and size), "ms": int((time.time()-t0)*1000),
                                  "size": size})
        except Exception as e:
            out["checks"].append({"name": name, "ok": False, "ms": int((time.time()-t0)*1000),
                                  "error": f"{type(e).__name__}: {str(e)[:160]}"})
    resp = jsonify(out)
    resp.headers["Cache-Control"] = "no-store"
    return resp


@app.route("/api/stats")
def api_stats():
    """👥 [v118] 로드맵 '초기 보급' 4순위 — 누적 분석 건수·방문자 수(사회적 증거).
       search_history를 그대로 집계하므로 별도 테이블이 필요 없다."""
    return jsonify(history_stats())


def _public_site_url():
    """공유·블로그 링크에 쓸 주소.
       🐛 [v119] "링크 만들기가 안 됨" 대응 — v118은 웹에서도 항상 chostock.kr로 링크를 만들어,
       도메인 연결 전에는 받은 사람이 링크를 열 수 없었다. 이제 웹 배포에서는 "지금 방문자가
       실제로 들어와 있는 주소"로 만들어 항상 열리게 하고(chostock.kr로 들어왔으면 chostock.kr),
       데스크톱(127.0.0.1)에서만 PUBLIC_SITE_URL을 쓴다. 둘 다 없으면 빈 값(=링크 생략)."""
    if _WEB_MODE:
        return request.host_url.rstrip("/")
    return PUBLIC_SITE_URL.rstrip("/") if PUBLIC_SITE_URL else ""


def _resolve_analysis_source(ticker, cached):
    """🚀 [v116/v118] `/api/ai-prompt`·`/api/blog-export`가 함께 쓰는 공용 로직.
       클라이언트가 방금 `/api/analyze`로 이미 받은 데이터(cached)를 그대로 보내면
       네이버를 다시 조회하지 않고 그 데이터를 그대로 쓰고, 없으면(GET, 캐시 형식이
       안 맞음 등) 기존처럼 서버가 직접 재조회한다 — 0단계에서 고친 "매번 재조회"
       버그를 새 기능에서 또 반복하지 않기 위해 이렇게 한 곳에 모아둔다.
       반환: (name, market, price_d, details, fundamentals, risk) 또는 실패 시 None."""
    if cached and cached.get("ticker") == ticker and cached.get("price"):
        name = cached.get("name") or ticker
        market = cached.get("market") or "—"
        price_d = cached.get("price")
        details = cached.get("details") or {}
        fundamentals = cached.get("fundamentals") or {}
        risk = cached.get("delisting_risk") or check_delisting_risk(
            price_d, details.get("risk_badges") or [], details.get("cap_eok"))
        return name, market, price_d, details, fundamentals, risk

    # 폴백 — 캐시 데이터가 없거나(분석 전에 버튼을 눌렀거나, 다른 종목으로 이미 넘어간
    # 경우 등) 형식이 안 맞으면 서버에서 구한다. ⚡ [v119] 서버 캐시에 있으면 그걸 쓴다.
    hit = _cache_get(("analyze", ticker))
    if hit:
        return (hit["name"], hit["market"], hit["price"], hit["details"], hit["fundamentals"],
                hit["delisting_risk"])
    name, market = get_ticker_info(ticker)
    if not name:
        name, live_market = get_ticker_name_live(ticker)
        market = market or live_market
        name = name or ticker
    price_d = get_price_data(ticker)
    if not price_d:
        return None
    details, fundamentals = get_company_details_and_fundamentals(ticker)
    risk = check_delisting_risk(price_d, details.get("risk_badges") or [], details.get("cap_eok"))
    return name, market, price_d, details, fundamentals, risk


@app.route("/api/ai-prompt/<ticker>", methods=["GET", "POST"])
def api_ai_prompt(ticker):
    if not FDR_OK:
        return jsonify({"error": "FinanceDataReader가 설치되어 있지 않습니다."}), 400
    ticker = normalize_ticker(ticker)
    cached = request.get_json(silent=True) if request.method == "POST" else None
    resolved = _resolve_analysis_source(ticker, cached)
    if not resolved:
        return jsonify({"error": "주가 데이터를 가져오지 못했습니다."}), 400
    name, market, price_d, details, fundamentals, risk = resolved
    prompt = build_ai_prompt(ticker, name, market or "—", price_d, fundamentals, details,
                              delisting_risk=risk)
    return jsonify({"prompt": prompt})


@app.route("/api/blog-export/<ticker>", methods=["GET", "POST"])
def api_blog_export(ticker):
    """📝 [v118] 로드맵 '초기 보급' 5순위 — AI에게 줄 프롬프트가 아니라, 사람이 그대로
       복사해서 블로그(네이버 블로그 등)에 붙여넣을 수 있는 완성된 글. AI 호출 없이
       지금 가진 수치만으로 즉시 만들어진다."""
    if not FDR_OK:
        return jsonify({"error": "FinanceDataReader가 설치되어 있지 않습니다."}), 400
    ticker = normalize_ticker(ticker)
    cached = request.get_json(silent=True) if request.method == "POST" else None
    resolved = _resolve_analysis_source(ticker, cached)
    if not resolved:
        return jsonify({"error": "주가 데이터를 가져오지 못했습니다."}), 400
    name, market, price_d, details, fundamentals, risk = resolved
    draft = build_blog_draft(ticker, name, market or "—", price_d, fundamentals, details,
                              delisting_risk=risk, site_url=_public_site_url())
    return jsonify({"draft": draft})


HTML_TEMPLATE = r"""
<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1,user-scalable=no">
<title>종목분석 미니 {{ app_version }}</title>
<script>window.__APP_VER__ = "{{ app_version }}"; window.__SITE_URL__ = "{{ site_url }}";
  window.__BRAND_URL__ = "{{ brand_url }}"; window.__BRAND_LABEL__ = "{{ site_label }}"; window.__BLOG_URL__ = "{{ blog_url }}";
  window.__ADS__ = {{ 'true' if ad_client else 'false' }};</script>
{% if ad_client %}<script async src="https://pagead2.googlesyndication.com/pagead/js/adsbygoogle.js?client={{ ad_client }}" crossorigin="anonymous"></script>{% endif %}
{% macro ad_slot(name) -%}
  {%- set sid = ad_slots.get(name, '') -%}
  {%- if ad_client and sid -%}
  <div class="adSlot" data-ad-name="{{ name }}"><div class="adLabel">광고</div><ins class="adsbygoogle" style="display:block" data-ad-client="{{ ad_client }}" data-ad-slot="{{ sid }}" data-ad-format="auto" data-full-width-responsive="true"></ins></div>
  {%- elif ad_preview -%}
  <div class="adSlot adPreview" data-ad-name="{{ name }}"><b>광고 자리 · {{ name }}</b><br><small>{{ ad_hints.get(name, '') }}</small></div>
  {%- endif -%}
{%- endmacro %}
<link rel="stylesheet" href="https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.9/dist/web/static/pretendard.css">
<script src="https://cdn.jsdelivr.net/npm/apexcharts"></script>
<style>
  :root{
    --navy:#10203a; --navy2:#16294a; --gold:#eab308;
    --up:#e11d48; --down:#2563eb;
    --bg:#f4f6fb; --card:#ffffff; --border:#e7eaf1;
    --text:#1a2233; --muted:#8993a4;
    --good:#16a34a; --warn:#eab308; --bad:#e11d48;
    --radius:16px;
  }
  *{box-sizing:border-box;}
  body{
    margin:0; background:var(--bg); color:var(--text);
    font-family:'Pretendard',-apple-system,BlinkMacSystemFont,'Malgun Gothic',sans-serif;
    -webkit-font-smoothing:antialiased;
  }
  .topbar{
    position:sticky; top:0; z-index:50; background:var(--navy);
    padding:14px 22px; display:flex; align-items:center; gap:12px; flex-wrap:wrap;
    box-shadow:0 2px 10px rgba(16,32,58,.18);
  }
  .brandBlock{display:flex; flex-direction:column; gap:1px;}
  .brand{color:#fff; font-weight:800; font-size:16px; white-space:nowrap; letter-spacing:-.2px;}
  .brand span{color:var(--gold);}
  .verTag{color:rgba(255,255,255,.4)!important; font-size:10px!important; font-weight:600!important; letter-spacing:0;}
  /* 📣 슬로건 태그 — 문구는 APP_SLOGAN 상수 하나만 바꾸면 여기와 첫 화면에 함께 반영됨 */
  .sloganTag{color:rgba(255,255,255,.55); font-size:10.5px; font-weight:600; white-space:nowrap;}
  .searchWrap{position:relative; flex:1; max-width:520px;}
  .searchInput{
    width:100%; box-sizing:border-box; border:none; border-radius:11px;
    padding:11px 16px; font-size:14px; outline:none;
    background:rgba(255,255,255,.12); color:#fff; font-family:inherit;
  }
  .searchInput::placeholder{color:rgba(255,255,255,.55);}
  .searchInput:focus{background:#fff; color:var(--text);}
  .searchDrop{
    position:absolute; top:calc(100% + 6px); left:0; right:0; background:#fff;
    border-radius:12px; box-shadow:0 12px 32px rgba(16,32,58,.22); overflow:hidden;
    display:none; max-height:340px; overflow-y:auto; z-index:60;
  }
  .searchDrop.show{display:block;}
  .searchItem{padding:10px 16px; cursor:pointer; display:flex; justify-content:space-between; align-items:center; font-size:13.5px;}
  .searchItem:hover{background:#f2f5fb;}
  .searchItem b{font-weight:700;}
  .marketPill{font-size:10px; font-weight:800; padding:2px 7px; border-radius:20px; color:#fff;}
  .mp-KOSPI{background:#10203a;} .mp-KOSDAQ{background:#0891b2;} .mp-other{background:#94a3b8;}
  .refreshBtn{
    background:rgba(255,255,255,.12); border:none; color:#fff; font-size:12px;
    padding:9px 14px; border-radius:10px; cursor:pointer; white-space:nowrap; font-family:inherit;
  }
  .refreshBtn:hover{background:rgba(255,255,255,.22);}
  .blogBtn{
    background:var(--gold); color:#1a2233; font-size:12.5px; font-weight:800;
    padding:9px 15px; border-radius:10px; text-decoration:none; white-space:nowrap;
    display:inline-flex; align-items:center; gap:5px;
  }
  .blogBtn:hover{background:#facc15;}

  .aiServiceBtn{
    border:none; border-radius:10px; padding:11px 16px; font-size:12.5px; font-weight:700;
    cursor:pointer; font-family:inherit; color:#fff; display:inline-flex; align-items:center; gap:6px;
  }
  .aiServiceBtn:hover{filter:brightness(1.08);}
  .as-gemini{background:linear-gradient(135deg,#4285f4,#9b72cb);}
  .as-chatgpt{background:#10a37f;}
  .as-claude{background:#c96442;}

  .wrap{max-width:980px; margin:0 auto; padding:22px 18px 70px;}
  .empty{
    text-align:center; color:var(--muted); padding:110px 20px 60px; font-size:14px; line-height:1.9;
  }
  .empty .big{font-size:40px; margin-bottom:14px;}
  .sloganLead{font-size:16px; font-weight:800; color:var(--navy); margin-bottom:8px;}

  /* ⏳ [v119] 분석 중 화면 — 무엇을 하고 있는지 보여줘서 기다림을 덜 지루하게 */
  .loadingCard{
    display:none; align-items:center; gap:14px; background:var(--card); border:1px solid var(--border);
    border-radius:var(--radius); padding:18px 20px; margin:0 0 16px; box-shadow:0 1px 3px rgba(16,32,58,.05);
  }
  .loadingCard.show{display:flex;}
  .spinner{width:28px; height:28px; border-radius:50%; border:3px solid #e3e8f0; border-top-color:var(--navy);
    animation:spin .8s linear infinite; flex:none;}
  @keyframes spin{to{transform:rotate(360deg);}}
  .loadingMsg{font-size:14px; font-weight:700; color:var(--navy);}
  .loadingSub{font-size:12px; color:var(--muted); margin-top:2px;}
  #result.dim{opacity:.45; transition:opacity .15s;}
  .errorCard{display:none; background:#fff1f2; border:1px solid #fecdd3; border-radius:var(--radius); padding:16px 20px; margin:0 0 16px;}
  .errorCard.show{display:block;}
  .errorMsg{font-size:14px; font-weight:800; color:#be123c;} .errorSub{font-size:12px; color:#9f1239; margin-top:3px;}
  .asOf.stale{color:#b45309; font-weight:700;}
  .asOf{font-size:11px; color:var(--muted); margin-top:4px;}

  /* 🔗 [v119] 공유 링크를 눈으로 확인하고 직접 복사할 수 있는 칸 */
  .shareLinkBox{display:none; gap:8px; align-items:center; margin:-10px 0 20px; flex-wrap:wrap;}
  .shareLinkBox.show{display:flex;}
  .shareLinkBox input{flex:1; min-width:220px; border:1px solid var(--border); border-radius:10px; padding:9px 12px;
    font-size:13px; font-family:inherit; background:#f8fafc; color:var(--text);}
  .shareLinkBox a{font-size:12.5px; color:#2563eb; font-weight:600;}

  /* 💰 [v119] 애드센스 자리 */
  .adSlot{margin:0 0 20px; text-align:center; min-height:0;}
  .adSlot .adLabel{font-size:10px; color:var(--muted); text-align:left; margin-bottom:2px;}
  .adPreview{border:2px dashed #94a3b8; border-radius:12px; padding:26px 12px; color:#64748b; font-size:12.5px; background:#f8fafc;}
  .whyGrid + .adSlot{max-width:760px; margin:24px auto 0;}

  /* 🤖 [v119] AI 안내창 */
  .aiGoBtn{display:block; text-align:center; text-decoration:none; border-radius:11px; padding:13px; font-size:14px;
    font-weight:800; color:#fff; background:#10a37f; margin-bottom:10px;}
  .aiGoBtn.as-gemini{background:linear-gradient(135deg,#4285f4,#9b72cb);} .aiGoBtn.as-claude{background:#c96442;}
  .aiGoBtn.as-chatgpt{background:#10a37f;}
  .aiSteps{margin:0; padding-left:20px;} .aiSteps li{margin:4px 0;}
  .pasteBox.pulse{outline:3px solid #8b5cf6; outline-offset:2px; animation:pulseBox 1.2s ease-in-out 3;}
  @keyframes pulseBox{50%{outline-color:#c4b5fd;}}
  .pasteHint{display:none; font-size:12.5px; color:#6d28d9; background:#f5f3ff; border:1px solid #ddd6fe;
    border-radius:10px; padding:9px 12px; margin:8px 0;}
  .pasteHint.show{display:block;}

  /* 📄 [v119] PDF 리포트(화면 밖에서 그려서 PDF로 변환) */
  .pdfReport{position:fixed; left:-12000px; top:0; background:#fff; padding:0; font-family:inherit;}
  .pdfReport .card{box-shadow:none;}
  .pdfTitleBox{padding:6px 2px 14px; border-bottom:2px solid var(--navy); margin-bottom:16px;}
  .pdfTitle{font-size:22px; font-weight:800; color:var(--navy);}
  .pdfSub{font-size:12px; color:var(--muted); margin-top:4px;}
  .pdfBanner{position:fixed; left:-12000px; top:0; width:760px; box-sizing:border-box; display:flex;
    align-items:center; justify-content:space-between; font-family:inherit;}
  .pdfBanner.head{height:64px; padding:0 18px; background:var(--navy); color:#fff; border-radius:10px;}
  .pdfBanner.foot{height:50px; padding:0 18px; background:#fff8db; color:#3c2f00; border:1px solid #f5d565; border-radius:10px;}
  .pdfBanner .bL{font-size:17px; font-weight:800;} .pdfBanner .bL small{display:block; font-size:11px; font-weight:600; opacity:.75;}
  .pdfBanner .bR{font-size:13px; font-weight:800; text-align:right;} .pdfBanner .bR small{display:block; font-size:11px; font-weight:600; opacity:.8;}
  .pdfBanner.head .bR{background:var(--gold); color:#1a1300; padding:8px 12px; border-radius:9px;}
  .pdfBanner.foot .bL{font-size:13px;}

  /* 📑 [v121] 재무정보 카드 */
  .finTabs{display:flex; gap:6px; margin:-4px 0 12px;}
  .finTab{border:1px solid var(--border); background:#f8fafc; border-radius:999px; padding:6px 14px; font-size:12px;
    font-weight:700; cursor:pointer; font-family:inherit; color:var(--muted);}
  .finTab.on{background:var(--navy); color:#fff; border-color:var(--navy);}
  .finTableWrap{overflow-x:auto;}
  .finTable{width:100%; border-collapse:collapse; font-size:12.5px; min-width:520px;}
  .finTable th, .finTable td{padding:7px 8px; border-bottom:1px solid #eef1f6; text-align:right; white-space:nowrap;}
  .finTable th:first-child, .finTable td:first-child{text-align:left; color:var(--navy); font-weight:700;}
  .finTable thead th{font-size:11.5px; color:var(--muted); font-weight:700; background:#f8fafc;}
  .finTable .est{color:#b45309; background:#fffbeb;}
  .finTable .yoy{display:block; font-size:10.5px; font-weight:600;}
  .finTable .up{color:var(--up);} .finTable .down{color:var(--down);}
  .finNote{font-size:11px; color:var(--muted); margin-top:8px; line-height:1.7;}
  .finGloss{margin-top:10px; font-size:11.5px; color:#475569; line-height:1.8; background:#f8fafc; border-radius:10px; padding:10px 12px;}

  /* 📰 [v121] 뉴스 카드 */
  .newsList{list-style:none; margin:0; padding:0;}
  .newsList li{padding:9px 0; border-bottom:1px solid #eef1f6; font-size:13px; line-height:1.55;}
  .newsList li:last-child{border-bottom:none;}
  .newsList a{color:var(--text); text-decoration:none; font-weight:600;}
  .newsList a:hover{text-decoration:underline;}
  .newsMeta{display:block; font-size:11px; color:var(--muted); font-weight:500; margin-top:2px;}
  .newsEmpty{font-size:12.5px; color:var(--muted);}

  /* 💡 [v121] 매력도 체크 */
  .voteCard{background:linear-gradient(135deg,#f5f3ff,#eef2ff); border:1px solid #ddd6fe; border-radius:var(--radius);
    padding:16px 18px; margin:0 0 20px;}
  .voteQ{font-size:14.5px; font-weight:800; color:var(--navy); margin-bottom:10px;}
  .voteBtns{display:flex; gap:8px; flex-wrap:wrap;}
  .voteBtn{flex:1; min-width:120px; border:2px solid transparent; background:#fff; border-radius:12px; padding:10px 8px;
    font-size:13.5px; font-weight:800; cursor:pointer; font-family:inherit; color:var(--text); box-shadow:0 1px 2px rgba(16,32,58,.06);}
  .voteBtn small{display:block; font-size:11px; font-weight:600; color:var(--muted); margin-top:2px;}
  .voteBtn.on.v-buy{border-color:var(--up); background:#fff1f2;} .voteBtn.on.v-watch{border-color:#eab308; background:#fefce8;}
  .voteBtn.on.v-pass{border-color:var(--down); background:#eff6ff;}
  .voteBar{display:flex; height:10px; border-radius:999px; overflow:hidden; margin:12px 0 6px; background:#e2e8f0;}
  .voteBar span{display:block; height:100%;} .vb-buy{background:var(--up);} .vb-watch{background:#eab308;} .vb-pass{background:var(--down);}
  .voteInfo{font-size:11.5px; color:#475569;}
  .topBox{max-width:640px; margin:22px auto 0; text-align:left; background:#fff; border:1px solid var(--border);
    border-radius:14px; padding:14px 16px;}
  .topBox ol{margin:6px 0 0; padding-left:22px;} .topBox li{font-size:13px; margin:5px 0; cursor:pointer;}
  .topBox li b{color:var(--navy);} .topBox li span{color:var(--muted); font-size:11.5px; margin-left:6px;}
  .recentClear{background:none; border:none; color:var(--muted); font-size:11px; cursor:pointer; text-decoration:underline;
    font-family:inherit; margin-left:8px; padding:0;}

  /* 🎬 [v118] 데모 버튼 — 슬로건 바로 아래, 눈에 띄지만 실제 검색창보다는 강조를 낮춘다 */
  .demoBtn{
    margin-top:16px; background:var(--navy); color:#fff; border:none; border-radius:999px;
    padding:10px 20px; font-size:13px; font-weight:700; cursor:pointer; font-family:inherit;
  }
  .demoBtn:hover{filter:brightness(1.12);}

  /* 👥 [v118] 누적 분석 건수 배지(사회적 증거) */
  .statsBadge{
    margin-top:14px; font-size:12px; color:var(--muted); background:#f8fafc;
    border:1px solid var(--border); border-radius:999px; display:inline-block; padding:6px 16px;
  }

  /* 🚀 [v117] 로드맵 1단계 — "최근 본 종목" 칩 목록(같은 브라우저면 재방문해도 유지) */
  .recentBox{max-width:640px; margin:28px auto 0; text-align:left;}
  .recentTitle{font-size:12.5px; font-weight:800; color:var(--navy); margin-bottom:8px;}
  .recentChips{display:flex; flex-wrap:wrap; gap:8px;}
  .recentChip{
    background:var(--card); border:1px solid var(--border); border-radius:999px;
    padding:7px 14px; font-size:12px; font-weight:600; color:var(--navy);
    cursor:pointer; white-space:nowrap;
  }
  .recentChip:hover{border-color:#94a3b8; background:#f8fafc;}
  .recentChip .rcMarket{color:var(--muted); font-weight:500; margin-left:4px;}

  /* 💡 [v107] "네이버 증권에 없는 잇점" 소개 카드 — 첫 화면·블로그 스크린샷용 */
  .whyGrid{
    display:grid; grid-template-columns:repeat(3, 1fr); gap:14px;
    max-width:760px; margin:36px auto 0; text-align:left;
  }
  .whyCard{
    background:var(--card); border:1px solid var(--border); border-radius:14px;
    padding:18px 16px; box-shadow:0 1px 3px rgba(16,32,58,.05);
  }
  .whyIcon{font-size:26px; margin-bottom:8px;}
  .whyTitle{font-size:13.5px; font-weight:800; color:var(--navy); margin-bottom:6px;}
  .whyDesc{font-size:11.5px; color:var(--muted); line-height:1.6;}
  @media (max-width:720px){ .whyGrid{grid-template-columns:1fr;} }

  .card{
    background:var(--card); border:1px solid var(--border); border-radius:var(--radius);
    padding:20px 22px; margin-bottom:16px; box-shadow:0 1px 3px rgba(16,32,58,.04);
  }
  .card h3{margin:0 0 14px; font-size:14px; font-weight:800; color:var(--navy); display:flex; align-items:center; gap:7px;}

  /* 헤더 카드 */
  .heroCard{display:flex; align-items:center; gap:26px; flex-wrap:wrap;}
  /* [v118] 공유 이미지로 저장될 때 출처가 함께 찍히도록 결과 카드 안에 둔 작은 표기 */
  .shareBrand{margin-top:10px; font-size:11px; font-weight:600; color:var(--muted);}
  .heroLeft{flex:1; min-width:220px;}
  .heroName{font-size:21px; font-weight:800; display:flex; align-items:center; gap:9px; flex-wrap:wrap;}
  .heroTicker{font-size:13px; color:var(--muted); font-weight:600; margin-top:2px;}
  .heroPrice{font-size:32px; font-weight:800; margin-top:12px; letter-spacing:-.5px;}
  .heroChange{font-size:14px; font-weight:700; margin-top:4px;}
  .up{color:var(--up);} .down{color:var(--down);} .flat{color:var(--muted);}

  /* 통계 그리드 */
  .statGrid{display:grid; grid-template-columns:repeat(auto-fill,minmax(140px,1fr)); gap:12px;}
  .statBox{background:#f8f9fc; border-radius:12px; padding:12px 14px;}
  .statLabel{font-size:11px; color:var(--muted); font-weight:700; margin-bottom:5px;}
  .statVal{font-size:16px; font-weight:800;}
  .statSub{font-size:10.5px; color:var(--muted); margin-top:3px;}

  /* 기술적 지표 용어 설명 */
  .indicatorGlossary{margin-top:16px; padding-top:14px; border-top:1px dashed #e2e8f0;}
  .igTitle{font-size:12px; font-weight:800; color:var(--muted); margin-bottom:8px; display:flex; justify-content:space-between; align-items:center;}
  .igTitle a{font-size:11px; font-weight:700; color:var(--navy); text-decoration:none;}
  .igTitle a:hover{text-decoration:underline;}
  .igItem{font-size:12px; line-height:1.75; color:#475569; margin-bottom:7px;}
  .igItem b{color:var(--navy); font-weight:800;}

  .badge{display:inline-block; font-size:10.5px; font-weight:800; padding:3px 9px; border-radius:20px;}
  .b-good{background:#dcfce7; color:var(--good);}
  .b-warn{background:#fef3c7; color:#a16207;}
  .b-bad{background:#fee2e2; color:var(--bad);}
  .b-neutral{background:#eef2f7; color:var(--muted);}

  #chartMain, #chartVol{width:100%;}

  .vpGrid{display:grid; grid-template-columns:repeat(3,1fr); gap:12px; margin-bottom:12px;}
  .vpBox{text-align:center; background:#f8f9fc; border-radius:12px; padding:14px 8px;}
  .vpBox .l{font-size:10.5px; color:var(--muted); font-weight:700;}
  .vpBox .v{font-size:16px; font-weight:800; margin-top:4px;}
  .vpNote{font-size:12.5px; color:var(--text); line-height:1.7; background:#f8f9fc; border-radius:10px; padding:12px 14px;}

  /* 💡 [v107] 동일업종 PEER 비교 + 애널리스트 컨센서스 카드 */
  .cardBadge{
    font-size:9.5px; font-weight:800; padding:2px 8px; border-radius:20px;
    background:#fef3c7; color:#b45309; border:1px solid #fde68a; margin-left:4px;
  }
  .consensusBox{
    background:#eff6ff; border:1px solid #bfdbfe; border-radius:12px;
    padding:12px 16px; margin-bottom:14px; font-size:12.5px; color:#1e3a8a; line-height:1.8;
  }
  .consensusBox b{font-size:15px;}
  .peerGrid{display:grid; grid-template-columns:repeat(3,1fr); gap:10px;}
  .peerItem{
    background:#f8f9fc; border-radius:10px; padding:10px 12px; cursor:pointer;
    transition:background .15s;
  }
  .peerItem:hover{background:#eef1f6;}
  .peerItem .nm{font-size:12px; font-weight:700; color:var(--navy);}
  .peerItem .pr{font-size:13px; font-weight:800; margin-top:3px;}
  .peerNote{font-size:11px; color:var(--muted); margin-top:10px;}
  @media (max-width:720px){ .peerGrid{grid-template-columns:repeat(2,1fr);} }

  .theoryBox{font-size:13px; line-height:1.9; color:#333;}
  .theoryBox b{color:var(--navy);}

  .overviewText{font-size:12.5px; line-height:1.8; color:#444; white-space:pre-line; margin-bottom:10px;}
  .revBreak{font-size:12px; color:var(--muted); line-height:1.8;}

  .aiBtnRow{display:flex; gap:8px; flex-wrap:wrap; margin-bottom:12px;}
  .btn{
    border:none; border-radius:10px; padding:10px 16px; font-size:12.5px; font-weight:700;
    cursor:pointer; font-family:inherit;
  }
  .btn-primary{background:var(--navy); color:#fff;}
  .btn-primary:hover{background:var(--navy2);}
  .btn-ghost{background:#eef2f7; color:var(--text);}
  .btn-ghost:hover{background:#e3e8f0;}
  .promptBox{
    width:100%; box-sizing:border-box; border:1.5px solid var(--border); border-radius:10px;
    padding:12px 14px; font-size:12px; line-height:1.7; font-family:inherit; color:#444;
    background:#f8f9fc; resize:vertical; min-height:120px;
  }
  .pasteBox{
    width:100%; box-sizing:border-box; border:1.5px solid var(--border); border-radius:10px;
    padding:12px 14px; font-size:12.5px; line-height:1.7; font-family:inherit; color:var(--text);
    resize:vertical; min-height:100px; margin-top:10px;
  }
  .aiResult{
    margin-top:14px; padding:22px 24px; background:linear-gradient(135deg,#f5f3ff,#eef2ff);
    border-radius:14px; font-size:15.5px; line-height:1.95; color:#1e1b3a; display:none;
    border:1px solid #ddd6fe;
  }
  .aiResult.show{display:block;}
  .aiResult .aiSection{
    font-size:16.5px; font-weight:800; color:#5b21b6; margin:22px 0 10px;
    padding-bottom:6px; border-bottom:2px solid #ddd6fe;
  }
  .aiResult .aiSection:first-child{margin-top:0;}
  .aiResult b{color:#4c1d95; font-weight:800;}
  .aiResult p{margin:6px 0;}
  .aiResult .aiBullet{display:block; margin:7px 0 7px 4px; padding-left:20px; position:relative;}
  .aiResult .aiBullet::before{content:'●'; position:absolute; left:0; top:8px; color:#8b5cf6; font-size:8px;}
  .aiHint{font-size:11px; color:var(--muted); margin-top:6px; line-height:1.7;}

  .footNote{text-align:center; font-size:11px; color:var(--muted); margin-top:26px; line-height:1.9;}

  .toast{
    position:fixed; bottom:26px; left:50%; transform:translateX(-50%) translateY(20px);
    background:var(--navy); color:#fff; padding:11px 20px; border-radius:30px; font-size:12.5px;
    font-weight:600; opacity:0; transition:all .25s; z-index:200; box-shadow:0 8px 24px rgba(0,0,0,.25);
    pointer-events:none; white-space:nowrap;
  }
  .toast.show{opacity:1; transform:translateX(-50%) translateY(0);}

  @media (max-width:640px){
    .heroCard{flex-direction:column; align-items:flex-start;}
  }

  /* 최초 이용 안내 및 면책 조항 — 동의 전에는 뒤 화면과 상호작용 불가 */
  .disclaimerOverlay{
    position:fixed; inset:0; z-index:1000; background:rgba(16,32,58,.72);
    display:flex; align-items:center; justify-content:center; padding:20px;
    backdrop-filter:blur(2px);
  }
  .disclaimerCard{
    background:#fff; border-radius:18px; max-width:560px; width:100%;
    max-height:88vh; display:flex; flex-direction:column; overflow:hidden;
    box-shadow:0 24px 60px rgba(0,0,0,.35);
  }
  .disclaimerHead{
    background:var(--navy); color:#fff; padding:20px 26px 18px;
  }
  .disclaimerHead h2{margin:0 0 4px; font-size:17px; font-weight:800;}
  .disclaimerHead p{margin:0; font-size:12px; color:rgba(255,255,255,.7);}
  .disclaimerBody{
    padding:20px 26px; overflow-y:auto; font-size:12.5px; line-height:1.85; color:#333;
  }
  .disclaimerBody h4{margin:16px 0 6px; font-size:13px; color:var(--navy); font-weight:800;}
  .disclaimerBody h4:first-child{margin-top:0;}
  .disclaimerBody p{margin:0 0 8px;}
  .disclaimerBody b{color:#b91c1c;}
  .disclaimerFoot{
    padding:16px 26px 22px; border-top:1px solid var(--border); background:#f8f9fc;
  }
  .disclaimerFoot label{
    display:flex; align-items:flex-start; gap:8px; font-size:12px; color:#555;
    margin-bottom:14px; cursor:pointer; line-height:1.6;
  }
  .disclaimerFoot label input{margin-top:3px; flex:none;}
  .agreeBtn{
    width:100%; box-sizing:border-box; border:none; border-radius:11px; padding:13px;
    background:var(--navy); color:#fff; font-size:13.5px; font-weight:800; cursor:pointer;
    font-family:inherit; transition:background .15s, opacity .15s;
  }
  .agreeBtn:disabled{opacity:.45; cursor:not-allowed;}
  .agreeBtn:not(:disabled):hover{background:var(--navy2);}
  .termsLink{
    background:none; border:none; color:var(--muted); font-size:11px; text-decoration:underline;
    cursor:pointer; font-family:inherit; padding:0;
  }

  /* 상세종목 분석 의뢰 CTA — 검색 직후 눈에 띄게 */
  .ctaBanner{
    display:flex; align-items:center; gap:14px; text-decoration:none;
    background:linear-gradient(135deg,#eab308,#f59e0b); border-radius:16px;
    padding:18px 22px; margin-bottom:16px; box-shadow:0 6px 20px rgba(234,179,8,.35);
    transition:transform .15s, box-shadow .15s; animation:ctaGlow 2.4s ease-in-out infinite;
  }
  .ctaBanner:hover{transform:translateY(-2px); box-shadow:0 10px 28px rgba(234,179,8,.5);}
  .ctaIcon{font-size:30px; flex:none; line-height:1;}
  .ctaText{flex:1;}
  .ctaTitle{font-size:14.5px; font-weight:800; color:#1a2233; line-height:1.4;}
  .ctaSub{font-size:12.5px; font-weight:700; color:#78350f; margin-top:3px;}
  .ctaArrow{font-size:20px; color:#78350f; flex:none;}
  @keyframes ctaGlow{
    0%,100%{box-shadow:0 6px 20px rgba(234,179,8,.35);}
    50%{box-shadow:0 6px 28px rgba(234,179,8,.62);}
  }

  /* 💡 [v107] 배너 슬롯 — 지금은 투자 팁, 추후 광고로 교체 가능하도록 독립된 블록 */
  .tipBanner{
    display:flex; align-items:center; gap:10px; background:#f8f9fc;
    border:1px dashed #d8deeb; border-radius:12px; padding:12px 18px;
    margin-bottom:16px; font-size:12px; color:var(--muted); line-height:1.6;
  }
  .tipBanner b{color:var(--navy);}

  /* 🚨 상장폐지 위험종목 경고 배너 — 결과 화면 맨 위, 가장 먼저 눈에 띄어야 함 */
  .riskBanner{
    display:flex; gap:14px; align-items:flex-start;
    background:linear-gradient(135deg,#fef2f2,#fee2e2); border:2px solid #ef4444;
    border-radius:14px; padding:18px 20px; margin-bottom:16px;
  }
  .riskBanner.level-caution{background:linear-gradient(135deg,#fffbeb,#fef3c7); border-color:#f59e0b;}
  .riskIcon{font-size:28px; flex:none; line-height:1.1;}
  .riskTextWrap{flex:1;}
  .riskTitle{font-size:15px; font-weight:800; color:#b91c1c; margin-bottom:8px;}
  .riskBanner.level-caution .riskTitle{color:#92400e;}
  .riskReasons{margin:0 0 9px; padding-left:20px; font-size:12.5px; color:#7f1d1d; line-height:1.85;}
  .riskBanner.level-caution .riskReasons{color:#78350f;}
  .riskNote{font-size:11px; color:#991b1b; line-height:1.6;}
  .riskBanner.level-caution .riskNote{color:#92400e;}
</style>
</head>
<body>

<div id="disclaimerOverlay" class="disclaimerOverlay">
  <div class="disclaimerCard">
    <div class="disclaimerHead">
      <h2>⚠️ 이용 안내 및 면책 조항</h2>
      <p>계속 이용하시려면 아래 내용을 읽고 동의해 주세요.</p>
    </div>
    <div class="disclaimerBody">
      <h4>1. 프로그램의 목적</h4>
      <p>이 프로그램(종목분석 미니)은 공개된 시세·재무 데이터를 기계적으로 계산·정리해서 보여주는
        <b>기술적 분석 참고용 도구</b>입니다. 자본시장법상 투자자문업·투자매매업 등으로 등록된 서비스가
        아니며, 특정 종목의 매수·매도·보유를 추천하거나 권유하지 않습니다.</p>

      <h4>2. 정보의 한계</h4>
      <p>화면에 표시되는 점수·차트·매물대·기업정보 등은 FinanceDataReader, 네이버금융 등 공개된
        데이터를 가공한 것으로, <b>실시간성·정확성·완전성을 보장하지 않습니다.</b> AI 분석 기능을 통해
        생성되는 내용 역시 이용자가 외부 AI 서비스에서 직접 받은 답변을 그대로 표시하는 것으로, 그
        정확성이나 적합성을 이 프로그램이 검증하지 않습니다.</p>

      <h4>3. 투자 판단 및 책임</h4>
      <p><b>모든 투자 판단과 매매, 그로 인한 결과(수익 또는 손실 포함)에 대한 책임은 전적으로 이용자
        본인에게 있습니다.</b> 이 프로그램의 제작자는 투자 결과에 대해 어떠한 책임도 지지 않습니다.</p>

      <h4>4. 면책 조항</h4>
      <p>이 프로그램의 설치·실행·이용 과정에서 발생하는 데이터 오류, 프로그램 오작동, 서비스 중단,
        제3자(FinanceDataReader·네이버금융·AI 서비스 등) 데이터·서비스의 문제, 그 밖에 이 프로그램의
        이용과 관련하여 발생하는 <b>직접적·간접적·부수적·특별·결과적 손해에 대하여 제작자는 민사상·
        형사상·상사상(상법상) 어떠한 책임도 지지 않습니다.</b> 이 프로그램의 이용으로 발생하는 모든
        문제에 대한 책임은 이용자 본인에게 있습니다.</p>

      <h4>5. 무상 제공 및 보증의 부인</h4>
      <p>이 프로그램은 무료로 제공되며 <b>"있는 그대로(AS-IS)"</b> 제공됩니다. 제작자는 특정 목적에의
        적합성, 상품성, 오류 없는 동작을 보증하지 않습니다.</p>

      <p style="margin-top:16px;color:#94a3b8;font-size:11px;">
        아래 [동의하고 시작하기] 버튼을 누르면 위 내용 전체에 동의한 것으로 간주됩니다.</p>
    </div>
    <div class="disclaimerFoot">
      <label><input type="checkbox" id="disclaimerCheck"> 위 이용 안내와 면책 조항을 모두 읽었으며, 이에 동의합니다.</label>
      <button id="agreeBtn" class="agreeBtn" disabled onclick="agreeDisclaimer()">동의하고 시작하기</button>
    </div>
  </div>
</div>

<div class="topbar">
  <div class="brandBlock">
    <div class="brand">📈 종목분석<span> 미니</span> <span class="verTag">{{ app_version }}</span></div>
    <div class="sloganTag">{{ slogan }}</div>
  </div>
  <div class="searchWrap">
    <input id="searchInput" class="searchInput" type="text" placeholder="종목명 또는 코드를 입력하세요 (예: 삼성전자, 005930)" autocomplete="off">
    <div id="searchDrop" class="searchDrop"></div>
  </div>
  <button class="refreshBtn" onclick="resetAll()" title="검색·결과·AI 칸을 모두 비우고 첫 화면으로 돌아갑니다">↺ 초기화</button>
  <button class="refreshBtn" onclick="refreshTickers()">🔄 종목목록 갱신</button>
  <a class="refreshBtn" href="/help" target="_blank" rel="noopener" style="text-decoration:none;">❓ 도움말</a>
  {% if kakao_url %}
  <a class="refreshBtn" href="{{ kakao_url }}" target="_blank" rel="noopener"
     style="text-decoration:none;background:#fee500;color:#3c1e1e;border-color:#fee500;"
     title="카카오톡 오픈채팅 커뮤니티에 참여해 보세요">💬 커뮤니티</a>
  {% endif %}
  <a class="blogBtn" href="{{ blog_url }}" target="_blank" rel="noopener"
     title="이 프로그램을 만든 제작자의 투자 블로그입니다">✍️ 제작자 블로그 ↗</a>
</div>

<div class="wrap">
  <!-- ⏳ [v119] 분석 중 표시 -->
  <!-- 🐛 [v120] 분석 실패 시 빈 화면 대신 이유와 [다시 시도]를 보여준다 -->
  <div id="errorCard" class="errorCard">
    <div class="errorMsg" id="errorMsg">주가 데이터를 가져오지 못했어요.</div>
    <div class="errorSub">네이버 응답이 잠시 늦는 경우가 많아요. 잠시 후 다시 눌러 주세요.</div>
    <div class="aiBtnRow" style="margin:10px 0 0;"><button class="btn btn-primary" onclick="retryAnalyze()">🔄 다시 시도</button>
      <button class="btn btn-ghost" onclick="hideError()">닫기</button></div>
  </div>
  <div id="loadingCard" class="loadingCard"><div class="spinner"></div>
    <div><div class="loadingMsg" id="loadingMsg">📈 주가 데이터를 불러오는 중…</div>
    <div class="loadingSub" id="loadingSub">보통 2~3초면 끝나요</div></div></div>

  <div id="emptyState" class="empty">
    <div class="big">🔍</div>
    <div class="sloganLead">{{ slogan }}</div>
    종목명이나 종목코드를 검색해서<br>기술적분석 리포트를 확인해 보세요.
    <div style="margin-top:18px;font-size:12px;">FinanceDataReader · 네이버 공개 데이터 기반 · 로그인 불필요</div>
    <div style="margin-top:6px;font-size:11.5px;">검색이 안 되면 6자리 종목코드(예: 005930)를 입력하고 Enter를 눌러도 바로 분석돼요.</div>

    <!-- 🎬 [v118] 로드맵 '초기 보급' 3순위 — 첫 방문자가 검색 없이 결과 화면을 바로
         체험하게 하는 데모 버튼(전환율 개선용). -->
    <button class="demoBtn" onclick="analyze('{{ demo_ticker }}')">🎬 데모로 먼저 보기 ({{ demo_name }})</button>

    <!-- 👥 [v118] 로드맵 '초기 보급' 4순위 — 누적 분석 건수로 사회적 증거를 보여준다.
         집계가 없거나(신규 배포 직후) 0건이면 자바스크립트가 그대로 숨겨둔다. -->
    <div id="statsBadge" class="statsBadge" style="display:none;"></div>

    <!-- 🚀 [v117] 로드맵 1단계 — 이 브라우저가 최근에 본 종목 칩 목록. 기록이 없으면
         (첫 방문 등) 자바스크립트가 style.display를 그대로 두어 보이지 않는다. -->
    <div id="recentBox" class="recentBox" style="display:none;">
      <div class="recentTitle">🕘 최근 본 종목 <button class="recentClear" onclick="clearRecent()">기록 지우기</button></div>
      <div id="recentChips" class="recentChips"></div>
    </div>

    <!-- 💡 [v121] 이번 주 매수 관심 TOP — 다른 이용자들이 '사고 싶어요'를 많이 누른 종목 -->
    <div id="topBox" class="topBox" style="display:none;">
      <div class="recentTitle">🔥 이번 주 매수 관심 TOP <span style="font-weight:500;color:var(--muted);font-size:11px;">— 이용자 투표 기준, 투자 권유 아님</span></div>
      <ol id="topList"></ol>
    </div>

    <!-- 💡 [v107] "네이버 증권에서 얻을 수 없는 잇점"을 첫 화면에서 바로 보여주는 소개 카드.
         블로그 홍보·첫인상용으로 스크린샷하기 좋게 구성했다. -->
    <div class="whyGrid">
      <div class="whyCard">
        <div class="whyIcon">🎯</div>
        <div class="whyTitle">매물대(Volume Profile) 분석</div>
        <div class="whyDesc">POC·지지선(VAL)·저항선(VAH)을 원 단위로 계산해 드립니다. 네이버 증권에는 없는 기관 트레이더급 분석 도구입니다.</div>
      </div>
      <div class="whyCard">
        <div class="whyIcon">🤖</div>
        <div class="whyTitle">무료 AI 종합 진단</div>
        <div class="whyDesc">뉴스 요약이 아니라, 기술적·밸류에이션 데이터를 종합한 전문 애널리스트 스타일 리포트를 API 키 없이 무료로 받아보세요.</div>
      </div>
      <div class="whyCard">
        <div class="whyIcon">🚨</div>
        <div class="whyTitle">위험 신호 조기 경보</div>
        <div class="whyDesc">동전주·거래정지 의심·시가총액 미달 등 관리종목 위험 신호를 종목 검색과 동시에 한눈에 보여드립니다.</div>
      </div>
    </div>
    {{ ad_slot('home_bottom') }}
    <div style="margin-top:22px;font-size:11px;"><a href="/privacy" style="color:var(--muted);">개인정보처리방침</a></div>
  </div>

  <div id="result" style="display:none;">

    <div id="riskBanner" class="riskBanner" style="display:none;">
      <div class="riskIcon">🚨</div>
      <div class="riskTextWrap">
        <div class="riskTitle" id="riskTitle">상장폐지 위험 경고</div>
        <ul class="riskReasons" id="riskReasons"></ul>
        <div class="riskNote">※ 이 경고는 공개 데이터를 근거로 한 참고 정보이며 확정적 판정이 아닙니다. 투자 전 반드시 KRX·DART 공시를 통해 직접 확인하세요.</div>
      </div>
    </div>

    <div class="card heroCard" id="shareCard">
      <div class="heroLeft">
        <div class="heroName" id="heroName">—</div>
        <div class="heroTicker" id="heroTicker">—</div>
        <div class="heroPrice" id="heroPrice">—</div>
        <div class="heroChange" id="heroChange">—</div>
        <div class="asOf" id="asOf"></div>
        {% if site_label %}<div class="shareBrand">📈 종목분석 미니 · {{ site_label }}</div>{% endif %}
      </div>
    </div>

    <!-- 🔗🖼️📝 [v118] 로드맵 '초기 보급' 2·5순위 — 공유(링크/이미지)·블로그 내보내기.
         AI 분석 카드와 같은 aiBtnRow/btn-ghost 스타일을 그대로 재사용한다. -->
    <div class="aiBtnRow" style="margin:0 0 20px;">
      <button class="btn btn-ghost" onclick="shareResult()">🔗 링크 공유</button>
      <button class="btn btn-ghost" onclick="shareResultImage()">🖼️ 이미지로 저장</button>
      <button class="btn btn-ghost" onclick="toggleBlogBox()">📝 블로그 내보내기</button>
      <button class="btn btn-primary" onclick="makePdfReport()">📄 PDF 리포트</button>
    </div>
    <div id="shareLinkBox" class="shareLinkBox">
      <input id="shareLinkInput" readonly onclick="this.select()">
      <button class="btn btn-ghost" onclick="copyShareLink()">📋 복사</button>
      <a id="shareLinkOpen" href="#" target="_blank" rel="noopener">열어보기 ↗</a>
    </div>
    <textarea id="blogDraftBox" class="promptBox" style="display:none;" readonly></textarea>

    <!-- 💡 [v121] 매력도 체크 — 이용자들의 매수 의도를 모은다(한 브라우저 한 표, 다시 누르면 취소) -->
    <div class="voteCard" id="voteCard">
      <div class="voteQ">💡 이 종목, 지금 사고 싶으세요?</div>
      <div class="voteBtns">
        <button class="voteBtn v-buy" data-vote="buy" onclick="castVote('buy')">👍 사고 싶어요<small id="vc-buy">0명</small></button>
        <button class="voteBtn v-watch" data-vote="watch" onclick="castVote('watch')">🤔 지켜볼래요<small id="vc-watch">0명</small></button>
        <button class="voteBtn v-pass" data-vote="pass" onclick="castVote('pass')">👎 아직은 아니에요<small id="vc-pass">0명</small></button>
      </div>
      <div class="voteBar"><span class="vb-buy" id="vb-buy" style="width:0"></span><span class="vb-watch" id="vb-watch" style="width:0"></span><span class="vb-pass" id="vb-pass" style="width:0"></span></div>
      <div class="voteInfo" id="voteInfo">아직 투표가 없어요. 첫 번째로 의견을 남겨 보세요!</div>
    </div>

    <a id="detailCta" class="ctaBanner" href="https://blog.naver.com/okykr/224284426807" target="_blank" rel="noopener">
      <div class="ctaIcon">🔎</div>
      <div class="ctaText">
        <div class="ctaTitle">이 종목, 더 깊이 있게 분석받고 싶으신가요?</div>
        <div class="ctaSub">✍️ 상세종목 분석 의뢰하기</div>
      </div>
      <div class="ctaArrow">→</div>
    </a>

    <!-- 💡 [v107] 광고 삽입 예정 영역 — 지금은 매 분석마다 바뀌는 유용한 투자 팁을
         보여주는 배너로 채워둔다(빈 공간이 아니라 그 자체로 가치 있게). 나중에 광고를
         붙일 때는 이 .tipBanner 블록만 교체하면 되고, 레이아웃 흐름(히어로카드 → 이
         배너 → 통계) 자체는 바뀌지 않도록 자리를 미리 잡아두었다. -->
    <div id="tipBanner" class="tipBanner"></div>
    {{ ad_slot('result_top') }}

    <div class="card">
      <h3>📊 기술적 지표</h3>
      <div class="statGrid" id="statGrid"></div>
      <div class="indicatorGlossary">
        <div class="igTitle">ℹ️ 지표 용어 설명 <a href="/help#sec-trend" target="_blank" rel="noopener">자세히 보기 →</a></div>
        <div class="igItem"><b>RSI(14)</b> 최근 14일간 가격 상승폭과 하락폭의 비율로 과매수·과매도를 가늠하는 지표입니다. 70 이상이면 과매수(단기 조정 가능성), 30 이하면 과매도(단기 반등 가능성) 구간으로 봅니다.</div>
        <div class="igItem"><b>이동평균 배열</b> 단기(5일)·중기(20일)·장기(60일) 이동평균선이 위에서부터 순서대로 놓인 모양입니다. 단기>중기>장기 순이면 '정배열'(상승 추세), 반대면 '역배열'(하락 추세)이라 부릅니다.</div>
        <div class="igItem"><b>거래량 배수</b> 오늘 거래량이 최근 20일 평균 거래량의 몇 배인지를 나타냅니다. 2배 이상이면 평소보다 관심이 크게 쏠렸다는 뜻으로, 상승·하락 어느 쪽이든 추세 전환의 신호로 참고됩니다.</div>
        <div class="igItem"><b>52주 위치</b> 최근 52주(1년) 동안의 최저가~최고가 구간에서 현재가가 몇 %에 위치하는지를 나타냅니다(0%=52주 최저, 100%=52주 최고). 낮을수록 저점권, 높을수록 고점권입니다.</div>
        <div class="igItem"><b>20일선 이격도</b> 현재가가 20일 이동평균선과 비교해 얼마나(%) 떨어져 있는지를 나타냅니다. 양수면 평균보다 위, 음수면 아래에 있다는 뜻으로, 절댓값이 클수록 단기적으로 평균 회귀(되돌림) 가능성이 커진다고 해석하기도 합니다.</div>
        <div class="igItem"><b>PER·PBR</b> PER(주가수익비율)은 주가를 주당순이익으로 나눈 값, PBR(주가순자산비율)은 주가를 주당순자산으로 나눈 값입니다. 둘 다 낮을수록 이익·자산 대비 주가가 저평가되어 있다고 해석되지만, 업종 평균과 함께 비교해야 의미가 있습니다.</div>
        <div class="igItem"><b>배당수익률</b> 1주당 연간 예상 배당금을 현재 주가로 나눈 비율입니다. 높을수록 주가 대비 배당 매력이 크다는 뜻이지만, 배당은 기업 상황에 따라 변경·중단될 수 있습니다.</div>
      </div>
    </div>

    <div class="card">
      <h3>📈 주가 차트 (최근 120거래일 · 일목균형표 구름 + 매물대 지지/저항선 포함)</h3>
      <div id="chartMain"></div>
      <div id="chartVol" style="margin-top:6px;"></div>
    </div>

    <div class="card" id="vpCard" style="display:none;">
      <h3>🎯 매물대 분석 (Volume Profile · 최근 60거래일)</h3>
      <div class="vpGrid">
        <div class="vpBox"><div class="l">VAL (지지)</div><div class="v" id="vpVal">—</div></div>
        <div class="vpBox"><div class="l">POC (최대매물가)</div><div class="v" id="vpPoc">—</div></div>
        <div class="vpBox"><div class="l">VAH (저항)</div><div class="v" id="vpVah">—</div></div>
      </div>
      <div class="vpNote" id="vpNote">—</div>
    </div>

    <div class="card">
      <h3>💡 기술적 해설</h3>
      <div class="theoryBox" id="theoryBox">—</div>
    </div>

    {{ ad_slot('result_middle') }}
    <div class="card" id="overviewCard" style="display:none;">
      <h3>🏢 기업개요 <span id="overviewSourceBadge" class="cardBadge" style="background:#f1f5f9;color:#64748b;border-color:#e2e8f0;"></span></h3>
      <div class="overviewText" id="overviewText"></div>
      <div class="revBreak" id="revBreak"></div>
    </div>

    <!-- 📑 [v121] 재무정보 -->
    <div class="card" id="finCard" style="display:none;">
      <h3>📑 재무 정보 <span class="cardBadge">연간·분기 실적</span></h3>
      <div class="finTabs"><button class="finTab on" data-p="annual" onclick="switchFin('annual')">연간</button>
        <button class="finTab" data-p="quarter" onclick="switchFin('quarter')">분기</button></div>
      <div id="finChart" style="min-height:220px;"></div>
      <div class="finTableWrap"><table class="finTable" id="finTable"></table></div>
      <div class="finNote">단위: 매출·이익 억원, 비율 %, EPS·BPS·배당 원 · <b style="color:#b45309;">노란 칸(E)</b>은 증권사 추정치 · 출처: 네이버 증권</div>
      <div class="finGloss"><b>읽는 법</b> · <b>영업이익률</b>: 매출 중 본업으로 남긴 이익 비율(높을수록 장사를 잘함) ·
        <b>ROE</b>: 자기 돈으로 1년에 몇 % 벌었는지(보통 10% 이상이면 양호) · <b>부채비율</b>: 자기 돈 대비 빚(100% 이하면 안정적인 편) ·
        <b>EPS</b>: 1주당 순이익 · <b>BPS</b>: 1주당 순자산</div>
    </div>

    <!-- 📰 [v121] 최근 2주 뉴스 -->
    <div class="card" id="newsCard" style="display:none;">
      <h3>📰 최근 2주 관련 뉴스 <span class="cardBadge" id="newsCount"></span></h3>
      <ul class="newsList" id="newsList"></ul>
      <div class="finNote">네이버 증권이 이 종목 관련으로 분류한 기사 중 최근 14일 이내만 보여줍니다. 제목을 누르면 기사가 열립니다.</div>
    </div>

    <div class="card" id="peerCard" style="display:none;">
      <h3>🤝 동일업종 비교 <span class="cardBadge">네이버 증권엔 없는 정보</span></h3>
      <div id="consensusBox" class="consensusBox" style="display:none;"></div>
      <div class="peerGrid" id="peerGrid"></div>
      <div class="peerNote">※ 가격·등락률만 제공됩니다(PER/PBR은 이 데이터 소스에서 확인되지 않아 표시하지 않습니다).</div>
    </div>

    <div class="card">
      <h3>🤖 AI 분석 (수동 모드)</h3>
      <div class="aiHint">이 앱은 AI를 직접 호출하지 않습니다. 아래 버튼을 누르는 순간 분석 프롬프트가
        <b>이미 복사</b>되어 있으니, 열리는 AI 화면에 <b>Ctrl+V(붙여넣기)</b>만 하시면 됩니다.
        AI 답변의 <b>복사</b> 버튼을 누르고 이 화면으로 돌아오면 답변이 아래 칸에 <b>자동으로</b> 들어가 정리됩니다.</div>
      <div class="aiBtnRow" style="margin-top:12px;">
        <button class="aiServiceBtn as-gemini" onclick="copyAndOpenAI('gemini')">🔷 제미나이로 분석</button>
        <button class="aiServiceBtn as-chatgpt" onclick="copyAndOpenAI('chatgpt')">🟢 챗GPT로 분석</button>
        <button class="aiServiceBtn as-claude" onclick="copyAndOpenAI('claude')">🟠 클로드로 분석</button>
      </div>
      <div class="aiBtnRow" style="margin-top:8px;">
        <button class="btn btn-ghost" onclick="copyAiPrompt()">📋 프롬프트만 복사</button>
        <button class="btn btn-ghost" onclick="toggleAiPromptBox()">프롬프트 보기/숨기기</button>
      </div>
      <textarea id="aiPromptBox" class="promptBox" style="display:none;" readonly></textarea>
      <div id="pasteHint" class="pasteHint">📥 AI 답변을 복사하셨다면 아래 <b>[복사한 답변 붙여넣기]</b>를 누르거나, 이 칸을 누르고 <b>Ctrl+V</b> 하세요.</div>
      <textarea id="aiPasteBox" class="pasteBox" placeholder="AI 답변이 여기에 자동으로 들어갑니다 — 안 들어오면 이 칸을 누르고 Ctrl+V 하세요."></textarea>
      <div class="aiBtnRow" style="margin-top:10px;">
        <button class="btn btn-primary" onclick="pasteAiAnswer(true)">📥 복사한 답변 붙여넣기</button>
        <button class="btn btn-ghost" onclick="renderAiResult()">🔄 다시 표시</button>
      </div>
      <div class="aiResult" id="aiResult"></div>
    </div>

    {{ ad_slot('result_bottom') }}
    <div class="footNote">
      본 리포트는 공개된 시세·재무 데이터를 기술적으로 계산한 참고 자료이며 투자 추천이 아닙니다.<br>
      투자 판단과 그 책임은 전적으로 투자자 본인에게 있습니다. · Data: FinanceDataReader, 네이버금융<br>
      <button class="termsLink" onclick="showDisclaimer(true)">이용 안내 및 면책 조항 다시 보기</button>
      · <a href="/privacy" class="termsLink" style="text-decoration:underline;">개인정보처리방침</a>
    </div>
  </div>
</div>

<!-- 🤖 [v119] AI 안내창 — 버튼을 누르는 순간 프롬프트는 이미 복사되어 있고, 이 창의
     [열기]는 진짜 링크라서 팝업 차단에 걸리지 않는다(브라우저 기본 alert 뒤에 새 창을 열면
     팝업 차단기가 막는 경우가 많아, alert 대신 같은 역할의 안내창을 쓴다). -->
<div id="aiGuideOverlay" class="disclaimerOverlay" style="display:none;" onclick="if(event.target===this)closeAiGuide()">
  <div class="disclaimerCard" style="max-width:460px;">
    <div class="disclaimerHead"><h2 id="aiGuideTitle">✅ 프롬프트가 복사되었습니다</h2>
      <p>아래 순서대로 하시면 AI 분석이 끝나요.</p></div>
    <div class="disclaimerBody">
      <ol class="aiSteps">
        <li>아래 <b id="aiGuideSvc">AI</b> 열기 버튼을 누르세요(새 창).</li>
        <li>입력칸을 누르고 <b>Ctrl+V</b>(휴대폰은 길게 눌러 <b>붙여넣기</b>) → 전송</li>
        <li>답변이 끝나면 답변 아래 <b>복사</b> 버튼(📋)을 누르세요.</li>
        <li>이 화면으로 돌아오면 답변이 <b>AI 분석 칸에 자동으로</b> 들어갑니다.</li>
      </ol>
    </div>
    <div class="disclaimerFoot">
      <a id="aiGoLink" class="aiGoBtn" href="#" target="_blank" rel="noopener" onclick="onAiGo()">AI 열기</a>
      <div class="aiBtnRow" style="margin:0 0 10px;">
        <button class="btn btn-ghost" onclick="recopyPrompt()">📋 다시 복사</button>
        <button class="btn btn-ghost" onclick="closeAiGuide()">닫기</button>
      </div>
      <label style="margin:0;"><input type="checkbox" id="aiGuideSkip"> 다음부터 이 안내 없이 바로 열기</label>
    </div>
  </div>
</div>

<div id="toast" class="toast"></div>

<script>
// ── 최초 이용 안내 및 면책 조항(동의 게이트) ─────────────────────────
// 스크립트가 실행되는 즉시(다른 어떤 로직보다 먼저) 확인해서, 이미 동의한
// 재방문자는 화면이 깜빡이지 않고 바로 앱을 쓸 수 있게 한다.
const DISCLAIMER_KEY = 'stockMiniDisclaimerAgreed_v1';
(function(){
  const overlay = document.getElementById('disclaimerOverlay');
  if(localStorage.getItem(DISCLAIMER_KEY) === '1'){
    overlay.style.display = 'none';
  }
})();

const disclaimerCheck = document.getElementById('disclaimerCheck');
const agreeBtn = document.getElementById('agreeBtn');
if(disclaimerCheck && agreeBtn){
  disclaimerCheck.addEventListener('change', function(){
    agreeBtn.disabled = !this.checked;
  });
}

function agreeDisclaimer(){
  try{ localStorage.setItem(DISCLAIMER_KEY, '1'); }catch(e){}
  document.getElementById('disclaimerOverlay').style.display = 'none';
}

// 이미 동의한 사용자가 하단 링크로 다시 열어볼 때도 체크박스와 버튼을 활성 상태로
// 보여준다(다시 훑어볼 수 있도록) — [동의하고 시작하기]를 누르면 그냥 닫힌다.
function showDisclaimer(reopen){
  const overlay = document.getElementById('disclaimerOverlay');
  overlay.style.display = 'flex';
  if(reopen){
    if(disclaimerCheck) disclaimerCheck.checked = true;
    if(agreeBtn) agreeBtn.disabled = false;
  }
}

let CUR = null;
let searchTimer = null;

// ── 🚀 [v117] 로드맵 1단계: 최근 본 종목 ──────────────────
let RECENT = [];

function renderRecentChips(){
  const box = document.getElementById('recentBox');
  const wrap = document.getElementById('recentChips');
  if(!RECENT.length){ box.style.display = 'none'; return; }
  wrap.innerHTML = RECENT.map(function(it){
    return '<div class="recentChip" data-ticker="' + _escHtml(it.ticker) + '">' + _escHtml(it.name)
      + '<span class="rcMarket">' + _escHtml(it.market || '') + '</span></div>';
  }).join('');
  Array.prototype.forEach.call(wrap.querySelectorAll('.recentChip'), function(el){
    el.onclick = function(){ analyze(el.getAttribute('data-ticker')); };
  });
  box.style.display = 'block';
}

// 페이지를 새로 열었을 때(새로고침·재방문) 서버(익명 uid 쿠키 기준)에서 한 번 불러온다.
function loadRecentHistory(){
  fetch('/api/history').then(r=>r.json()).then(list=>{
    if(Array.isArray(list)) { RECENT = list; renderRecentChips(); }
  }).catch(()=>{});
}

// 분석에 성공할 때마다, 서버를 다시 조회하지 않고 이 목록 맨 앞에 바로 반영한다
// (같은 종목이 이미 있으면 그 자리를 빼고 맨 앞으로 올림 — 중복 표시 방지).
function addRecentLocal(item){
  RECENT = RECENT.filter(function(it){ return it.ticker !== item.ticker; });
  RECENT.unshift(item);
  RECENT = RECENT.slice(0, 8);
  renderRecentChips();
}

loadRecentHistory();

// ── 👥 [v118] 로드맵 '초기 보급' 4순위: 누적 분석 건수 배지 ──────
function loadStats(){
  fetch('/api/stats').then(r=>r.json()).then(d=>{
    if(!d || !d.total_analyses){ return; }  // 배포 직후(0건)에는 굳이 보여주지 않는다.
    const badge = document.getElementById('statsBadge');
    badge.textContent = '👥 지금까지 ' + d.unique_visitors.toLocaleString('ko-KR') + '명이 '
      + d.total_analyses.toLocaleString('ko-KR') + '건의 종목을 분석했어요';
    badge.style.display = 'inline-block';
  }).catch(()=>{});
}
loadStats();
loadVoteTop();
window.addEventListener('load', ()=>pushAds(document.getElementById('emptyState')));

// ── 🔗 [v118] 공유 링크로 들어온 경우(?t=종목코드) 자동으로 그 종목을 분석 ──
// 🐛 [v119] 스크립트 전체가 준비된 뒤(DOMContentLoaded)에 실행 — 바로 실행하면 아래쪽에 선언된
// 변수(_CLIENT_CACHE 등)가 아직 없어 공유 링크로 들어와도 분석이 시작되지 않았다.
window.addEventListener('DOMContentLoaded', function(){
  const t = new URLSearchParams(location.search).get('t');
  if(t) analyze(t);
});

function showToast(msg){
  const t = document.getElementById('toast');
  t.textContent = msg;
  t.classList.add('show');
  clearTimeout(t._h);
  t._h = setTimeout(()=>t.classList.remove('show'), 2600);
}

function fmt(n){
  if(n === null || n === undefined || isNaN(n)) return '—';
  return Math.round(n).toLocaleString('ko-KR');
}

// ── 검색 ─────────────────────────────────
const searchInput = document.getElementById('searchInput');
const searchDrop = document.getElementById('searchDrop');

searchInput.addEventListener('input', function(){
  clearTimeout(searchTimer);
  const q = this.value.trim();
  if(!q){ searchDrop.classList.remove('show'); return; }
  searchTimer = setTimeout(()=>doSearch(q), 280);
});
searchInput.addEventListener('keydown', function(e){
  if(e.key === 'Enter'){
    // 🚀 [v105] 검색 결과가 "정확히 1개"일 때만 Enter로 바로 적용한다. 여러 개가 뜬
    //   상태에서 무작정 첫 번째 것으로 넘어가면 원치 않는 종목이 선택될 수 있어서다.
    const items = searchDrop.querySelectorAll('.searchItem[data-ticker]');
    if(items.length === 1){
      items[0].click();
      return;
    }
    if(items.length > 1){
      showToast('검색 결과가 여러 개입니다. 원하는 종목을 선택해 주세요.');
      return;
    }
    // 🐛 [v103] 6자리 종목코드를 직접 입력하면 바로 분석할 수 있게 한다 — 캐시가 채워지길
    //   기다릴 필요가 없다. 예전엔 숫자만 남기고 걸러서(\D 제거) 2024년 개편 이후의
    //   영숫자 혼용 코드(예: 0011T0, 채비)를 인식하지 못했다 — 영문자도 함께 허용.
    const code = this.value.replace(/[^0-9A-Za-z]/g, '').toUpperCase();
    if(code.length === 6){
      searchDrop.classList.remove('show');
      analyze(code);
    }
  }
});
document.addEventListener('click', function(e){
  if(!e.target.closest('.searchWrap')) searchDrop.classList.remove('show');
});

function doSearch(q){
  fetch('/api/search?q=' + encodeURIComponent(q)).then(r=>r.json()).then(list=>{
    if(!Array.isArray(list)) list = [];
    const code = q.replace(/[^0-9A-Za-z]/g, '').toUpperCase();
    let html = list.map(function(it){
      const mCls = it.market === 'KOSPI' ? 'mp-KOSPI' : (it.market === 'KOSDAQ' ? 'mp-KOSDAQ' : 'mp-other');
      return '<div class="searchItem" data-ticker="' + it.ticker + '" data-name="' + it.name.replace(/"/g,'&quot;') + '">'
        + '<span><b>' + it.name + '</b> <span style="color:#94a3b8;">' + it.ticker + '</span></span>'
        + '<span class="marketPill ' + mCls + '">' + (it.market||'—') + '</span>'
        + '</div>';
    }).join('');
    // 6자리 코드를 입력했는데 캐시에 없으면 "코드로 바로 분석" 항목을 추가로 보여준다.
    if(code.length === 6 && !list.some(function(it){ return it.ticker === code; })){
      html += '<div class="searchItem" data-ticker="' + code + '" data-name="' + code + '" style="background:#f8fafc;">'
        + '<span>🔎 코드로 바로 분석: <b>' + code + '</b></span></div>';
    }
    if(!html){
      html = '<div class="searchItem" style="color:#94a3b8;">검색 결과가 없습니다. 6자리 종목코드를 알고 계시면 직접 입력해 Enter를 눌러보세요.<br>또는 상단의 [🔄 종목목록 갱신]을 눌러보세요.</div>';
    }
    searchDrop.innerHTML = html;
    searchDrop.classList.add('show');
    Array.prototype.forEach.call(searchDrop.querySelectorAll('.searchItem[data-ticker]'), function(el){
      el.onclick = function(){
        searchInput.value = el.getAttribute('data-name');
        searchDrop.classList.remove('show');
        analyze(el.getAttribute('data-ticker'));
      };
    });
  }).catch(()=>{});
}

function refreshTickers(){
  showToast('🔄 종목목록을 갱신하는 중입니다...');
  fetch('/api/refresh-tickers', {method:'POST'}).then(r=>r.json()).then(d=>{
    showToast(d.msg || '요청을 보냈습니다.');
  }).catch(()=>showToast('갱신 요청 중 오류가 발생했습니다.'));
}

// ── 분석 실행 ─────────────────────────────
// ⚡ [v119] 분석 — 로딩 화면을 보여주고, 같은 종목을 2분 안에 다시 보면 서버에도 묻지 않고
// 즉시 보여준다(최근 본 종목 칩을 오가며 볼 때 체감 속도가 크게 좋아짐).
const _CLIENT_CACHE = {};
let _analyzing = null;
let _loadingTimer = null;
const _LOADING_STEPS = ['📈 주가 데이터를 불러오는 중…', '🏢 기업 정보를 확인하는 중…', '🎯 매물대와 지표를 계산하는 중…', '📝 리포트를 정리하는 중…'];

function _showLoading(on){
  const card = document.getElementById('loadingCard');
  clearInterval(_loadingTimer);
  if(!on){ card.classList.remove('show'); document.getElementById('result').classList.remove('dim'); return; }
  let i = 0, started = Date.now();
  document.getElementById('loadingMsg').textContent = _LOADING_STEPS[0];
  document.getElementById('loadingSub').textContent = '보통 2~3초면 끝나요';
  card.classList.add('show');
  document.getElementById('result').classList.add('dim');
  window.scrollTo({top: 0, behavior: 'smooth'});
  _loadingTimer = setInterval(()=>{
    i = Math.min(i + 1, _LOADING_STEPS.length - 1);
    document.getElementById('loadingMsg').textContent = _LOADING_STEPS[i];
    if(Date.now() - started > 7000)
      document.getElementById('loadingSub').textContent = '평소보다 오래 걸리고 있어요. 네이버 응답을 기다리는 중입니다…';
  }, 900);
}

function analyze(ticker){
  ticker = String(ticker || '').trim().toUpperCase();
  if(!ticker) return;
  const hit = _CLIENT_CACHE[ticker] || _CLIENT_CACHE[ticker.padStart(6, '0')];
  if(hit && Date.now() - hit.t < 120000){ _applyAnalysis(hit.data); return; }
  if(_analyzing === ticker) return;   // 같은 종목 연타 방지
  _analyzing = ticker;
  _lastTried = ticker;
  hideError();
  _showLoading(true);
  fetch('/api/analyze/' + encodeURIComponent(ticker)).then(r=>r.json()).then(data=>{
    if(data.error){ showError(data.error); return; }
    if(!data.stale) _CLIENT_CACHE[data.ticker] = { t: Date.now(), data: data };
    _applyAnalysis(data);
    if(data.stale) showToast('⚠ 네이버 응답이 늦어 ' + data.as_of + ' 기준 데이터를 보여드려요.');
  }).catch(()=>showError('서버에 연결하지 못했어요. 인터넷 연결을 확인해 주세요.'))
    .finally(()=>{ _analyzing = null; _showLoading(false); });
}

// 🐛 [v120] 실패 안내 상자
let _lastTried = null;
function showError(msg){
  document.getElementById('errorMsg').textContent = '⚠ ' + msg;
  document.getElementById('errorCard').classList.add('show');
  window.scrollTo({top: 0, behavior: 'smooth'});
}
function hideError(){ document.getElementById('errorCard').classList.remove('show'); }
function retryAnalyze(){ if(_lastTried) analyze(_lastTried); }

function _applyAnalysis(data){
    CUR = data;
    addRecentLocal({ ticker: data.ticker, name: data.name, market: data.market });
    // 🐛 [v108] result를 먼저 연 뒤 렌더링하고, 한 구간의 실패가 다른 구간까지 끌고
    // 내려가지 않도록 renderResult 내부도 구간별로 보호한다.
    document.getElementById('emptyState').style.display = 'none';
    document.getElementById('result').style.display = 'block';
    try{
      renderResult(data);
    }catch(e){
      console.error('[renderResult]', e);
      showToast('⚠ 일부 항목 표시 중 오류가 있었지만 나머지는 정상 표시됩니다.');
    }
    const asOf = document.getElementById('asOf');
    const dd = data.details || {};
    const srcName = {naver_api: '네이버', fdr: '네이버', fchart: '네이버', yahoo: '야후 파이낸스(약 15~20분 지연 가능)'}[dd.price_source] || '';
    asOf.textContent = data.as_of ? ('데이터 기준 ' + data.as_of + ' (한국 시간)' + (srcName ? ' · 시세 출처 ' + srcName : '')
      + (data.stale ? ' · 최신 데이터를 못 가져와 이전 결과를 표시 중' : '')) : '';
    if(dd.partial && !data.stale) showToast('⚠ 네이버 연결이 불안정해 시세는 야후에서 가져왔고, 기업정보·뉴스 일부는 빠졌어요.');
    asOf.classList.toggle('stale', !!data.stale);
    document.getElementById('aiPromptBox').value = '';
    document.getElementById('aiPromptBox').style.display = 'none';
    document.getElementById('blogDraftBox').value = '';
    document.getElementById('blogDraftBox').style.display = 'none';
    document.getElementById('shareLinkBox').classList.remove('show');
    document.getElementById('aiPasteBox').value = '';
    document.getElementById('aiResult').classList.remove('show');
    document.getElementById('pasteHint').classList.remove('show');
    AI_PENDING = null;
    _prefetchPrompt();                 // 🤖 [v119] AI 버튼을 누르기 전에 프롬프트를 미리 준비
    setTimeout(()=>pushAds(document.getElementById('result')), 50);
}

function renderResult(data){
  const p = data.price, f = data.fundamentals || {}, d = data.details || {};

  // 🚨 상장폐지 위험 경고 배너 — 위험이 없으면(level:'none') 숨긴다
  const riskBanner = document.getElementById('riskBanner');
  const risk = data.delisting_risk || {level:'none', reasons:[]};
  if(risk.level === 'danger' || risk.level === 'caution'){
    riskBanner.className = 'riskBanner' + (risk.level === 'caution' ? ' level-caution' : '');
    document.getElementById('riskTitle').textContent = risk.level === 'danger'
      ? '🚨 상장폐지 위험 경고 — 거래상태 이상 신호가 감지되었습니다'
      : '⚠️ 상장폐지 위험 주의 — 정황상 의심되는 신호가 있습니다';
    document.getElementById('riskReasons').innerHTML = (risk.reasons || []).map(function(r){
      return '<li>' + _escHtml(r) + '</li>';
    }).join('');
    riskBanner.style.display = 'flex';
  } else {
    riskBanner.style.display = 'none';
  }

  document.getElementById('heroName').innerHTML = data.name +
    ' <span class="marketPill ' + (data.market==='KOSPI'?'mp-KOSPI':(data.market==='KOSDAQ'?'mp-KOSDAQ':'mp-other')) + '">' + (data.market||'—') + '</span>';
  document.getElementById('heroTicker').textContent = data.ticker;
  document.getElementById('heroPrice').textContent = fmt(p.price) + '원';
  const dp = p.day_pct || 0;
  const dCls = dp > 0 ? 'up' : (dp < 0 ? 'down' : 'flat');
  document.getElementById('heroChange').innerHTML =
    '<span class="' + dCls + '">' + (dp>0?'▲ +':dp<0?'▼ ':'') + dp + '%</span>'
    + '<span style="color:#8993a4;font-weight:500;"> · 전일 ' + fmt(p.prev) + '원</span>';

  // 통계 그리드
  const stats = [];
  stats.push(['RSI(14)', p.rsi, p.rsi>=70?'b-bad':p.rsi<=30?'b-good':'b-neutral', p.rsi>=70?'과매수':p.rsi<=30?'과매도':'중립']);
  stats.push(['이동평균 배열', p.ma_align, p.ma_align==='정배열'?'b-good':p.ma_align==='역배열'?'b-bad':'b-neutral', '']);
  stats.push(['거래량 배수', (p.vol_ratio||0)+'배', p.vol_ratio>=2?'b-warn':'b-neutral', '20일 평균 대비']);
  stats.push(['52주 위치', (p.pos52||0)+'%', p.pos52>=85?'b-warn':p.pos52<=15?'b-good':'b-neutral', '0=최저 100=최고']);
  stats.push(['20일선 이격도', (p.ma20_diff>0?'+':'')+p.ma20_diff+'%', '', '']);
  stats.push(['5일/20일 등락률', p.pct5+'% / '+p.pct20+'%', '', '']);
  if(p.bb_squeeze) stats.push(['변동성', '스퀴즈 감지', 'b-warn', '방향성 돌파 전조']);
  if(f.PER) stats.push(['PER', f.PER + (f.sector_PER?(' (업종 '+f.sector_PER+')'):''), '', '']);
  if(f.PBR) stats.push(['PBR', f.PBR, '', '']);
  if(f.DIV) stats.push(['배당수익률', f.DIV+'%', '', '']);
  if(d.market_cap && d.market_cap!=='N/A') stats.push(['시가총액', d.market_cap, '', '']);
  if(d.sector && d.sector!=='—') stats.push(['업종', d.sector, '', '']);

  document.getElementById('statGrid').innerHTML = stats.map(function(s){
    return '<div class="statBox"><div class="statLabel">'+s[0]+'</div><div class="statVal">'+s[1]
      + (s[2] ? ' <span class="badge '+s[2]+'">'+s[3]+'</span>' : '')
      + '</div></div>';
  }).join('');

  drawCharts(p.chart, p.vp);

  // 매물대
  if(p.vp && p.vp.poc){
    document.getElementById('vpCard').style.display = 'block';
    document.getElementById('vpVal').textContent = fmt(p.vp.val)+'원';
    document.getElementById('vpPoc').textContent = fmt(p.vp.poc)+'원';
    document.getElementById('vpVah').textContent = fmt(p.vp.vah)+'원';
    document.getElementById('vpNote').textContent = '현재가 위치: ' + p.vp.va_pos + ' (POC 대비 ' + p.vp.poc_diff_str + ')';
  } else {
    document.getElementById('vpCard').style.display = 'none';
  }

  document.getElementById('theoryBox').innerHTML = p.theory_text || '—';

  if(d.overview || d.revenue_breakdown){
    document.getElementById('overviewCard').style.display = 'block';
    document.getElementById('overviewText').textContent = d.overview || '';
    document.getElementById('revBreak').textContent = d.revenue_breakdown ? ('주요 매출구성: ' + d.revenue_breakdown) : '';
    // 🐛 [v108] 출처 배지 — 네이버에서 실제 개요를 가져왔는지, 리포트 제목 대체인지,
    // 아니면 AI 분석을 기다리는 중인지 한눈에 알 수 있게 표시한다.
    const srcBadge = document.getElementById('overviewSourceBadge');
    if(srcBadge){
      const srcMap = { naver:'네이버 제공', naver_reports:'참고: 증권사 리포트 제목', ai_pending:'AI 분석 대기중' };
      srcBadge.textContent = srcMap[d.overview_source] || '';
    }
  } else {
    document.getElementById('overviewCard').style.display = 'none';
  }

  // 💡 [v107] 동일업종 PEER 비교 + 애널리스트 컨센서스 — 네이버 증권 PC 화면에는
  // 없는 정보라 별도 카드로 눈에 띄게 보여준다. PEER를 클릭하면 그 종목으로 바로
  // 이동해서 비교 탐색이 자연스럽게 이어지도록 했다(체류시간·재방문에도 도움).
  const peers = d.peers || [];
  const consensus = d.consensus;
  if(peers.length || consensus){
    document.getElementById('peerCard').style.display = 'block';
    const cbox = document.getElementById('consensusBox');
    if(consensus && consensus.target_price){
      cbox.style.display = 'block';
      const gap = p.price ? ((consensus.target_price - p.price) / p.price * 100) : null;
      cbox.innerHTML = '📊 증권사 목표주가 평균 <b>' + fmt(consensus.target_price) + '원</b>'
        + (gap !== null ? (' <span style="color:' + (gap>=0?'#dc2626':'#2563eb') + ';font-weight:700;">(현재가 대비 ' + (gap>=0?'+':'') + gap.toFixed(1) + '%)</span>') : '')
        + (consensus.date ? ('<br><span style="font-size:10.5px;opacity:.75;">' + consensus.date + ' 기준 · 증권사 평균 전망이며 실제와 다를 수 있습니다</span>') : '');
    } else {
      cbox.style.display = 'none';
    }
    document.getElementById('peerGrid').innerHTML = peers.map(function(pe){
      const pdp = pe.day_pct;
      const pCls = pdp > 0 ? 'up' : (pdp < 0 ? 'down' : '');
      return '<div class="peerItem" onclick="searchInput.value=\''+_escHtml(pe.name)+'\'; analyze(\''+pe.ticker+'\');">'
        + '<div class="nm">' + _escHtml(pe.name) + '</div>'
        + '<div class="pr ' + pCls + '">' + (pe.price!=null?fmt(pe.price)+'원':'—')
        + (pdp!=null ? ' <span style="font-size:10.5px;">(' + (pdp>=0?'+':'') + pdp.toFixed(2) + '%)</span>' : '') + '</div>'
        + '</div>';
    }).join('');
  } else {
    document.getElementById('peerCard').style.display = 'none';
  }

  // 💡 [v107] 배너 슬롯 — 분석마다 투자 팁을 하나씩 무작위로 보여준다(추후 광고 교체용 자리).
  const TIPS = [
    '💡 RSI가 30 이하면 과매도, 70 이상이면 과매수 구간으로 흔히 해석됩니다.',
    '💡 매물대(Volume Profile)의 POC는 최근 가장 많은 거래가 쌓인 가격대로, 강한 지지·저항으로 작용하는 경우가 많습니다.',
    '💡 이동평균선이 정배열(단기>중기>장기)이면 상승 추세, 역배열이면 하락 추세로 흔히 해석됩니다.',
    '💡 목표주가는 증권사들의 평균 전망일 뿐, 실제 주가와 크게 다를 수 있습니다.',
    '💡 거래량이 평소보다 크게 늘며 상승하면 매집, 크게 늘며 하락하면 물량 이탈 신호로 보는 시각이 있습니다.',
    '💡 이 프로그램의 AI 분석은 참고용입니다 — 최종 투자 판단은 스스로 여러 자료를 함께 확인하고 내려주세요.',
  ];
  document.getElementById('tipBanner').innerHTML = TIPS[Math.floor(Math.random()*TIPS.length)];

  try{ renderFinancials(d.financials); }catch(e){ console.error('[fin]', e); }
  try{ renderNews(d.news); }catch(e){ console.error('[news]', e); }
  loadVotes(data.ticker);
}

// ── 📑 [v121] 재무정보 ───────────────────────────────────────────
let _FIN = null, _finPeriod = 'annual', _finChart = null;
function _num(v, digits){
  if(v === null || v === undefined) return '—';
  return Number(v).toLocaleString('ko-KR', {maximumFractionDigits: digits == null ? 2 : digits});
}
function renderFinancials(fin){
  _FIN = fin || null;
  const has = fin && ((fin.annual && fin.annual.periods) || (fin.quarter && fin.quarter.periods));
  document.getElementById('finCard').style.display = has ? 'block' : 'none';
  if(!has) return;
  switchFin(fin.annual ? 'annual' : 'quarter');
}
function switchFin(period){
  _finPeriod = period;
  document.querySelectorAll('.finTab').forEach(b=>b.classList.toggle('on', b.getAttribute('data-p') === period));
  const f = _FIN && _FIN[period];
  const tbl = document.getElementById('finTable');
  if(!f || !f.periods){ tbl.innerHTML = '<tr><td>데이터 없음</td></tr>'; return; }
  const heads = f.periods.map(p=>p.title + (p.estimate ? '(E)' : ''));
  const money = {'매출액':1,'영업이익':1,'당기순이익':1};
  let html = '<thead><tr><th>항목</th>' + f.periods.map((p,i)=>'<th class="' + (p.estimate?'est':'') + '">' + _escHtml(heads[i]) + '</th>').join('') + '</tr></thead><tbody>';
  f.rows.forEach(r=>{
    html += '<tr><td>' + _escHtml(r.name) + '</td>' + r.values.map((v,i)=>{
      let yoy = '';
      if(money[r.name] && i > 0 && v != null && r.values[i-1]){
        const g = (v / r.values[i-1] - 1) * 100;
        if(isFinite(g)) yoy = '<span class="yoy ' + (g>=0?'up':'down') + '">' + (g>=0?'+':'') + g.toFixed(1) + '%</span>';
      }
      const digits = money[r.name] || r.name === 'EPS' || r.name === 'BPS' || r.name === '주당배당금' ? 0 : 2;
      return '<td class="' + (f.periods[i].estimate?'est':'') + '">' + _num(v, digits) + yoy + '</td>';
    }).join('') + '</tr>';
  });
  tbl.innerHTML = html + '</tbody>';
  // 매출액·영업이익 막대 + 영업이익률 선
  try{
    const get = n=>(f.rows.find(r=>r.name===n) || {values: []}).values;
    const el = document.getElementById('finChart');
    if(_finChart){ try{ _finChart.destroy(); }catch(e){} _finChart = null; }
    el.innerHTML = '';
    if(typeof ApexCharts === 'undefined') return;
    _finChart = new ApexCharts(el, {
      chart: {type: 'line', height: 230, toolbar: {show: false}, fontFamily: 'inherit', animations: {enabled: false}},
      series: [
        {name: '매출액(억원)', type: 'column', data: get('매출액')},
        {name: '영업이익(억원)', type: 'column', data: get('영업이익')},
        {name: '영업이익률(%)', type: 'line', data: get('영업이익률')},
      ],
      labels: heads, colors: ['#94a3b8', '#10203a', '#e11d48'],
      stroke: {width: [0, 0, 3]}, markers: {size: 4}, dataLabels: {enabled: false},
      plotOptions: {bar: {columnWidth: '55%', borderRadius: 3}},
      yaxis: [
        {seriesName: '매출액(억원)', labels: {formatter: v=>v==null?'':Math.round(v).toLocaleString('ko-KR')}},
        {seriesName: '매출액(억원)', show: false},
        {seriesName: '영업이익률(%)', opposite: true, labels: {formatter: v=>v==null?'':v.toFixed(0) + '%'}},
      ],
      legend: {position: 'top', fontSize: '11px'}, grid: {borderColor: '#eef1f6'},
      tooltip: {shared: true, y: {formatter: v=>v==null?'—':Number(v).toLocaleString('ko-KR')}},
    });
    _finChart.render();
  }catch(e){ console.error('[finChart]', e); }
}

// ── 📰 [v121] 최근 2주 뉴스 ──────────────────────────────────────
function renderNews(news){
  const card = document.getElementById('newsCard');
  const list = document.getElementById('newsList');
  card.style.display = 'block';
  news = news || [];
  document.getElementById('newsCount').textContent = news.length ? news.length + '건' : '';
  if(!news.length){ list.innerHTML = '<li class="newsEmpty">최근 2주 동안 이 종목 관련 뉴스가 없어요.</li>'; return; }
  list.innerHTML = news.map(n=>'<li><a href="' + _escHtml(n.url) + '" target="_blank" rel="noopener">' + _escHtml(n.title) + '</a>'
    + '<span class="newsMeta">' + _escHtml(n.date) + ' · ' + _escHtml(n.press) + (n.related ? ' · 관련 기사 ' + n.related + '건' : '') + '</span></li>').join('');
}

// ── 💡 [v121] 매력도 체크 ────────────────────────────────────────
function _renderVotes(v){
  if(!v || !v.counts) return;
  const c = v.counts, total = v.total || 0;
  ['buy','watch','pass'].forEach(k=>{
    document.getElementById('vc-' + k).textContent = (c[k] || 0) + '명';
    document.getElementById('vb-' + k).style.width = total ? ((c[k] || 0) / total * 100) + '%' : '0';
  });
  document.querySelectorAll('.voteBtn').forEach(b=>b.classList.toggle('on', b.getAttribute('data-vote') === v.mine));
  document.getElementById('voteInfo').textContent = total
    ? '최근 ' + v.days + '일 ' + total + '명 참여 · 👍 매수 관심 ' + Math.round((c.buy || 0) / total * 100) + '%'
      + (v.mine ? ' · 내 선택을 다시 누르면 취소돼요' : '') + ' · 참고용이며 투자 권유가 아닙니다'
    : '아직 투표가 없어요. 첫 번째로 의견을 남겨 보세요!';
}
function loadVotes(ticker){
  fetch('/api/vote/' + encodeURIComponent(ticker)).then(r=>r.json()).then(v=>{
    if(CUR && CUR.ticker === ticker) _renderVotes(v);
  }).catch(()=>{});
}
function castVote(choice){
  if(!CUR) return;
  const cur = document.querySelector('.voteBtn.on');
  const vote = (cur && cur.getAttribute('data-vote') === choice) ? null : choice;   // 같은 걸 또 누르면 취소
  const ticker = CUR.ticker;
  fetch('/api/vote/' + encodeURIComponent(ticker), {method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({vote: vote, name: CUR.name})}).then(r=>r.json()).then(v=>{
    if(v.error){ showToast('⚠ ' + v.error); return; }
    if(CUR && CUR.ticker === ticker) _renderVotes(v);
    showToast(vote ? '🙌 의견이 반영됐어요!' : '투표를 취소했어요.');
  }).catch(()=>showToast('⚠ 저장하지 못했어요.'));
}
function loadVoteTop(){
  fetch('/api/vote-top').then(r=>r.json()).then(list=>{
    if(!Array.isArray(list) || !list.length) return;
    document.getElementById('topList').innerHTML = list.map(t=>'<li data-ticker="' + _escHtml(t.ticker) + '"><b>' + _escHtml(t.name || t.ticker)
      + '</b><span>👍 ' + t.buys + '명 / 참여 ' + t.total + '명</span></li>').join('');
    document.querySelectorAll('#topList li').forEach(li=>li.onclick = ()=>analyze(li.getAttribute('data-ticker')));
    document.getElementById('topBox').style.display = 'block';
  }).catch(()=>{});
}

// ── ↺ [v121] 초기화 — 첫 화면으로 돌아가고 검색·결과·AI 칸을 모두 비운다 ──
function resetAll(){
  CUR = null; CUR_PROMPT = null; AI_PENDING = null; _lastTried = null;
  searchInput.value = ''; searchDrop.classList.remove('show');
  hideError(); _showLoading(false);
  ['aiPromptBox','blogDraftBox','aiPasteBox'].forEach(id=>{ const el = document.getElementById(id); el.value = ''; });
  document.getElementById('aiPromptBox').style.display = 'none';
  document.getElementById('blogDraftBox').style.display = 'none';
  document.getElementById('aiResult').classList.remove('show');
  document.getElementById('aiResult').innerHTML = '';
  document.getElementById('pasteHint').classList.remove('show');
  document.getElementById('shareLinkBox').classList.remove('show');
  if(_finChart){ try{ _finChart.destroy(); }catch(e){} _finChart = null; }
  document.getElementById('result').style.display = 'none';
  document.getElementById('emptyState').style.display = 'block';
  if(location.search) history.replaceState(null, '', location.pathname);
  window.scrollTo({top: 0, behavior: 'smooth'});
  loadRecentHistory(); loadStats(); loadVoteTop();
  searchInput.focus();
  showToast('↺ 초기화했어요.');
}
function clearRecent(){
  if(!confirm('이 브라우저의 최근 본 종목 기록을 모두 지울까요?')) return;
  fetch('/api/history', {method: 'DELETE'}).then(r=>r.json()).then(()=>{
    RECENT = []; renderRecentChips(); showToast('🧹 최근 본 종목을 지웠어요.');
  }).catch(()=>showToast('⚠ 지우지 못했어요.'));
}

function drawCharts(c, vp){
  if(!c || !c.dates || !c.dates.length) return;
  // 🐛 [v108] ApexCharts는 CDN에서 불러오므로(네트워크 상황에 따라 실패할 수 있음),
  // 여기서 예외가 나도 다른 화면 요소까지 끌고 내려가지 않도록 격리한다.
  if(typeof ApexCharts === 'undefined'){
    document.getElementById('chartMain').innerHTML =
      '<div style="padding:30px;text-align:center;color:#94a3b8;font-size:12px;">📉 차트 라이브러리를 불러오지 못했습니다(인터넷 연결을 확인해 주세요). 다른 정보는 정상적으로 표시됩니다.</div>';
    document.getElementById('chartVol').innerHTML = '';
    return;
  }
  try{
    // 🐛 [v113] 구름(선행스팬)은 실제 거래일(c.dates)보다 26일 더 미래까지 그려지므로
    // (c.cloud_dates가 더 김), category형 x축으로는 두 길이가 어긋난다. datetime형
    // x축으로 바꿔 각 시리즈가 실제 시각(ms)을 기준으로 알아서 정렬되도록 한다.
    const toTs = function(dt){ return new Date(dt + 'T00:00:00').getTime(); };

    const candleData = c.dates.map(function(dt,i){
      return { x: toTs(dt), y: [c.open[i], c.high[i], c.low[i], c.close[i]] };
    });
    const volData = c.dates.map(function(dt,i){ return { x: toTs(dt), y: c.volume[i] }; });
    const maLine = function(arr,name,color){
      return { name: name, type: 'line', data: c.dates.map(function(dt,i){ return { x: toTs(dt), y: arr[i] }; }), color: color };
    };

    document.getElementById('chartMain').innerHTML = '';
    document.getElementById('chartVol').innerHTML = '';

    // ── 일목균형표 구름(선행스팬 A/B) — [v113] 신설 ──────────────
    // rangeArea 시리즈로 두 선(A/B) 사이를 색칠해 '구름' 띠 모양으로 표시한다.
    // 구름은 정의상 26거래일 앞으로 투영되므로 c.cloud_dates가 c.dates보다 길다.
    const hasCloud = c.cloud_dates && c.cloud_dates.length && c.senkou_a && c.senkou_b;
    const series = [ { name:'주가', type:'candlestick', data: candleData } ];
    const fillOpacity = [1];
    const strokeWidth = [1];

    if(hasCloud){
      const cloudBand = c.cloud_dates.map(function(dt,i){
        const a = c.senkou_a[i], b = c.senkou_b[i];
        if(a==null || b==null) return { x: toTs(dt), y: [null,null] };
        return { x: toTs(dt), y: [Math.min(a,b), Math.max(a,b)] };
      });
      series.push({ name:'구름(선행스팬A/B)', type:'rangeArea', data: cloudBand, color:'#8b5cf6' });
      fillOpacity.push(0.18); strokeWidth.push(0);
      series.push({ name:'선행스팬A', type:'line', data: c.cloud_dates.map(function(dt,i){ return { x: toTs(dt), y: c.senkou_a[i] }; }), color:'#16a34a' });
      fillOpacity.push(1); strokeWidth.push(1.5);
      series.push({ name:'선행스팬B', type:'line', data: c.cloud_dates.map(function(dt,i){ return { x: toTs(dt), y: c.senkou_b[i] }; }), color:'#e11d48' });
      fillOpacity.push(1); strokeWidth.push(1.5);
    }
    if(c.tenkan){
      series.push({ name:'전환선(9)', type:'line', data: c.dates.map(function(dt,i){ return { x: toTs(dt), y: c.tenkan[i] }; }), color:'#0ea5e9' });
      fillOpacity.push(1); strokeWidth.push(1.5);
    }
    if(c.kijun){
      series.push({ name:'기준선(26)', type:'line', data: c.dates.map(function(dt,i){ return { x: toTs(dt), y: c.kijun[i] }; }), color:'#f59e0b' });
      fillOpacity.push(1); strokeWidth.push(1.5);
    }

    series.push(maLine(c.ma5,'MA5','#f59e0b')); fillOpacity.push(1); strokeWidth.push(1.5);
    series.push(maLine(c.ma20,'MA20','#2563eb')); fillOpacity.push(1); strokeWidth.push(1.5);
    series.push(maLine(c.ma60,'MA60','#16a34a')); fillOpacity.push(1); strokeWidth.push(1.5);

    // ── 매물대(Volume Profile) POC·VAL·VAH — [v113] 신설 ──────────
    // 기존엔 텍스트 카드로만 안내되던 지지/저항 가격대를 차트 위 수평선으로도 표시한다.
    const yAnnotations = [];
    if(vp && vp.poc){
      yAnnotations.push({ y: vp.poc, borderColor:'#8993a4', strokeDashArray:0,
        label:{ text:'POC '+Math.round(vp.poc).toLocaleString('ko-KR'), style:{ background:'#8993a4', color:'#fff', fontSize:'10px' }, position:'left' } });
      yAnnotations.push({ y: vp.vah, borderColor:'#e11d48', strokeDashArray:4,
        label:{ text:'VAH(저항) '+Math.round(vp.vah).toLocaleString('ko-KR'), style:{ background:'#e11d48', color:'#fff', fontSize:'10px' }, position:'left' } });
      yAnnotations.push({ y: vp.val, borderColor:'#2563eb', strokeDashArray:4,
        label:{ text:'VAL(지지) '+Math.round(vp.val).toLocaleString('ko-KR'), style:{ background:'#2563eb', color:'#fff', fontSize:'10px' }, position:'left' } });
    }

    new ApexCharts(document.getElementById('chartMain'), {
      chart: { type:'candlestick', height:400, toolbar:{show:false}, group:'stk' },
      series: series,
      xaxis: { type:'datetime', labels:{ show:false } },
      yaxis: { tooltip:{enabled:true}, labels:{ formatter:function(v){ return Math.round(v).toLocaleString('ko-KR'); } } },
      plotOptions: { candlestick: { colors: { upward:'#e11d48', downward:'#2563eb' } } },
      fill: { opacity: fillOpacity },
      stroke: { width: strokeWidth, curve:'straight' },
      legend: { show:true, fontSize:'11px', position:'top', horizontalAlign:'right' },
      grid: { borderColor:'#eef1f6' },
      annotations: { yaxis: yAnnotations },
      tooltip: { shared:true }
    }).render();

    new ApexCharts(document.getElementById('chartVol'), {
      chart: { type:'bar', height:100, toolbar:{show:false}, group:'stk' },
      series: [ { name:'거래량', data: volData } ],
      xaxis: { type:'datetime', labels:{ show:false } },
      yaxis: { labels:{ formatter:function(v){ return (v/10000).toFixed(0)+'만'; } } },
      plotOptions: { bar:{ columnWidth:'70%' } },
      colors: ['#c7cede'],
      grid: { borderColor:'#eef1f6' },
      dataLabels: { enabled:false }
    }).render();
  }catch(e){
    console.error('[drawCharts]', e);
    document.getElementById('chartMain').innerHTML =
      '<div style="padding:30px;text-align:center;color:#94a3b8;font-size:12px;">📉 차트를 그리는 중 오류가 발생했습니다. 다른 정보는 정상적으로 표시됩니다.</div>';
  }
}

// ── AI 수동 분석 ─────────────────────────
const AI_SERVICE_URLS = {
  gemini:  'https://gemini.google.com/app',
  chatgpt: 'https://chatgpt.com/',
  claude:  'https://claude.ai/new',
};
const AI_SERVICE_NAMES = { gemini:'제미나이', chatgpt:'챗GPT', claude:'클로드' };

// 🐛 [v119] 예전엔 clipboard.writeText가 "나중에 실패"해도 즉시 true를 돌려줘서, 복사가 안 됐는데
// "복사되었습니다"라고 안내하는 경우가 있었다. 이제 클릭 순간 바로 끝나는 방식(execCommand)을
// 먼저 쓰고 그 결과를 그대로 알려주며, 최신 방식(clipboard.writeText)은 보조로 함께 시도한다.
function _copyText(text){
  let ok = false;
  try{
    const ta = document.createElement('textarea');
    ta.value = text; ta.setAttribute('readonly', '');
    ta.style.cssText = 'position:fixed;left:-9999px;top:0;opacity:0;';
    document.body.appendChild(ta);
    ta.focus({preventScroll:true}); ta.select(); ta.setSelectionRange(0, text.length);
    ok = document.execCommand('copy');
    document.body.removeChild(ta);
  }catch(e){ ok = false; }
  try{
    if(navigator.clipboard && navigator.clipboard.writeText && window.isSecureContext){
      navigator.clipboard.writeText(text).catch(()=>{});
      if(!ok) ok = true;   // execCommand가 막힌 최신 브라우저 — writeText가 처리
    }
  }catch(e){}
  return ok;
}

function _openExternal(url){
  // <a target="_blank"> 클릭 방식이 window.open()보다 데스크톱 창 앱(pywebview) 환경에서
  // 기본 브라우저로 안정적으로 열리는 경우가 많아 이 방식을 사용한다.
  const a = document.createElement('a');
  a.href = url; a.target = '_blank'; a.rel = 'noopener';
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
}

// 🚀 [v116] 로드맵 0단계(0-3) — `/api/ai-prompt`를 부르는 세 함수(copyAndOpenAI·
//   copyAiPrompt·toggleAiPromptBox)가 전부 이 헬퍼를 함께 쓴다. CUR(방금 /api/analyze로
//   받은 분석 결과)을 그대로 POST로 실어 보내, 서버가 네이버를 다시 조회하지 않고
//   이미 있는 데이터로만 프롬프트를 만들게 한다 — 예전엔 이 요청마다 가격·기업개요·
//   재무를 처음부터 다시 긁어와서 몇 초씩 걸렸다.
function _fetchAiPrompt(){
  return fetch('/api/ai-prompt/' + CUR.ticker, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(CUR),
  }).then(r=>r.json());
}

// 🤖 [v119] AI 버튼 — "누르는 순간 프롬프트가 이미 복사되어 있게".
//   분석이 끝나자마자 프롬프트를 미리 만들어 CUR_PROMPT에 넣어 두고(_prefetchPrompt),
//   버튼을 누르면 그 자리에서 곧바로 복사한다(기다림 없음 → 브라우저가 복사를 막지 않음).
//   그다음 안내창을 띄우고, 안내창의 [열기]는 진짜 링크라 팝업 차단에 걸리지 않는다.
//   "다음부터 안내 없이"를 고르면 복사와 동시에 바로 새 창을 연다.
let CUR_PROMPT = null;
let AI_PENDING = null;
let _AI_WHICH = 'chatgpt';
const AI_GUIDE_SKIP_KEY = 'stockMiniAiGuideSkip_v1';

function _prefetchPrompt(){
  CUR_PROMPT = null;
  if(!CUR) return;
  const want = CUR.ticker;
  _fetchAiPrompt().then(d=>{
    if(CUR && CUR.ticker === want && d && d.prompt){
      CUR_PROMPT = d.prompt;
      document.getElementById('aiPromptBox').value = d.prompt;
    }
  }).catch(()=>{});
}

function _guideSkipped(){ try{ return localStorage.getItem(AI_GUIDE_SKIP_KEY) === '1'; }catch(e){ return false; } }

function _markAiPending(){
  AI_PENDING = { t: Date.now(), prompt: CUR_PROMPT || '' };
  document.getElementById('pasteHint').classList.add('show');
}

function copyAndOpenAI(which){
  if(!CUR){ showToast('먼저 종목을 분석해 주세요.'); return; }
  _AI_WHICH = which;
  const svc = AI_SERVICE_NAMES[which] || which;
  if(!CUR_PROMPT){
    // 분석 직후 아주 짧은 순간(0.1초 안팎)에만 생길 수 있다 — 준비되면 안내창에서 이어서 진행.
    showToast('⏳ 프롬프트를 준비하는 중이에요…');
    _fetchAiPrompt().then(d=>{
      if(d && d.prompt){ CUR_PROMPT = d.prompt; document.getElementById('aiPromptBox').value = d.prompt; _openAiGuide(which, false); }
      else showToast('⚠ ' + ((d && d.error) || '프롬프트를 만들지 못했습니다.'));
    }).catch(()=>showToast('⚠ 프롬프트 생성 중 오류가 발생했습니다.'));
    return;
  }
  const ok = _copyText(CUR_PROMPT);
  if(_guideSkipped()){
    _openExternal(AI_SERVICE_URLS[which]);
    _markAiPending();
    showToast(ok ? '📋 복사 완료 — ' + svc + ' 입력칸에 Ctrl+V 하세요.' : '⚠ 복사가 막혔어요. [프롬프트만 복사]를 눌러 주세요.');
    return;
  }
  _openAiGuide(which, ok);
}

function _openAiGuide(which, copied){
  const svc = AI_SERVICE_NAMES[which] || which;
  document.getElementById('aiGuideTitle').textContent = copied
    ? '✅ 프롬프트가 복사되었습니다' : '📋 아래 [열기]를 누르면 복사와 함께 열립니다';
  document.getElementById('aiGuideSvc').textContent = svc;
  const link = document.getElementById('aiGoLink');
  link.href = AI_SERVICE_URLS[which];
  link.className = 'aiGoBtn as-' + which;
  link.textContent = svc + ' 열기 →';
  document.getElementById('aiGuideSkip').checked = false;
  document.getElementById('aiGuideOverlay').style.display = 'flex';
}

function closeAiGuide(){ document.getElementById('aiGuideOverlay').style.display = 'none'; }

// 안내창의 [열기] — 진짜 링크 클릭이라 새 창은 브라우저가 알아서 연다. 여기서는 한 번 더 복사
// (새 클릭이라 확실히 허용됨)하고, "다음부터 안내 없이" 설정과 답변 자동 붙여넣기 대기를 기록한다.
function onAiGo(){
  if(CUR_PROMPT) _copyText(CUR_PROMPT);
  try{ if(document.getElementById('aiGuideSkip').checked) localStorage.setItem(AI_GUIDE_SKIP_KEY, '1'); }catch(e){}
  _markAiPending();
  setTimeout(closeAiGuide, 150);
}

function recopyPrompt(){
  showToast(CUR_PROMPT && _copyText(CUR_PROMPT) ? '📋 다시 복사했어요.' : '⚠ 복사가 막혔어요. [프롬프트 보기]에서 직접 복사해 주세요.');
}

// ── 🤖 [v119] AI 답변 자동 붙여넣기 ────────────────────────────
//   AI 사이트에서 답변을 복사한 뒤 이 탭으로 돌아오면(창 포커스) 클립보드를 읽어 AI 칸에 넣는다.
//   브라우저가 클립보드 읽기를 허락하지 않으면(파이어폭스·사파리·창 앱 등) 버튼과 Ctrl+V 안내를 띄운다.
function _looksLikeAnswer(txt){
  const prompt = ((AI_PENDING && AI_PENDING.prompt) || CUR_PROMPT || '').trim();
  return txt && txt.length >= 80 && txt !== prompt && txt !== aiPasteBoxEl.value.trim()
    && !(prompt && txt.slice(0, 60) === prompt.slice(0, 60));
}
function _applyPastedAnswer(txt){
  aiPasteBoxEl.value = txt;
  renderAiResult();
  AI_PENDING = null;
  document.getElementById('pasteHint').classList.remove('show');
  aiPasteBoxEl.classList.remove('pulse');
  showToast('🤖 AI 답변을 붙여넣고 정리했어요.');
}
function pasteAiAnswer(fromClick){
  if(!(navigator.clipboard && navigator.clipboard.readText)){
    if(fromClick) showToast('이 브라우저는 자동 붙여넣기를 지원하지 않아요. 칸을 누르고 Ctrl+V 해 주세요.');
    aiPasteBoxEl.classList.add('pulse'); aiPasteBoxEl.focus();
    return;
  }
  navigator.clipboard.readText().then(txt=>{
    txt = (txt || '').trim();
    if(_looksLikeAnswer(txt)){ _applyPastedAnswer(txt); return; }
    if(fromClick) showToast('클립보드에 AI 답변이 없어요. AI 화면에서 답변 아래 복사 버튼을 먼저 눌러 주세요.');
  }).catch(()=>{
    document.getElementById('pasteHint').classList.add('show');
    aiPasteBoxEl.classList.add('pulse');
    if(fromClick){ showToast('브라우저가 클립보드 읽기를 막았어요. 칸을 누르고 Ctrl+V 해 주세요.'); aiPasteBoxEl.focus(); }
  });
}
let _returnTimer = null;
function _onReturnToTab(){
  if(!AI_PENDING || Date.now() - AI_PENDING.t > 30 * 60 * 1000) return;
  clearTimeout(_returnTimer);
  _returnTimer = setTimeout(()=>pasteAiAnswer(false), 350);
}
window.addEventListener('focus', _onReturnToTab);
document.addEventListener('visibilitychange', ()=>{ if(document.visibilityState === 'visible') _onReturnToTab(); });

function copyAiPrompt(){
  if(!CUR){ showToast('먼저 종목을 분석해 주세요.'); return; }
  _fetchAiPrompt().then(d=>{
    if(d.error){ showToast('⚠ ' + d.error); return; }
    const box = document.getElementById('aiPromptBox');
    box.value = d.prompt;
    box.style.display = 'block';
    box.focus(); box.select();
    const copied = _copyText(d.prompt);
    showToast(copied ? '📋 프롬프트가 복사되었습니다. AI 챗봇에 붙여넣으세요.' : '📋 아래 프롬프트를 직접 선택해 복사해 주세요.');
  }).catch(()=>showToast('⚠ 프롬프트 생성 중 오류가 발생했습니다.'));
}

function toggleAiPromptBox(){
  const box = document.getElementById('aiPromptBox');
  if(box.style.display === 'none'){
    if(!box.value && CUR){
      _fetchAiPrompt().then(d=>{
        if(d.prompt) box.value = d.prompt;
        box.style.display = 'block';
      });
    } else {
      box.style.display = 'block';
    }
  } else {
    box.style.display = 'none';
  }
}

// ── 🔗🖼️📝 [v118] 로드맵 '초기 보급' 2·5순위: 공유·이미지 저장·블로그 내보내기 ──

// 지금 보고 있는 종목으로 바로 돌아오는 공유 링크(?t=종목코드). 다른 브라우저에서 이
// 링크로 들어오면 위쪽 "?t= 자동 분석" 코드가 곧바로 같은 결과 화면을 띄워준다.
// 🐛 [v119] 방문자가 실제로 들어와 있는 주소를 쓴다(그래야 항상 열린다). 내 PC 창 앱
// (127.0.0.1)에서만 공개 주소(chostock.kr)를 대신 쓴다.
function _isLocalHost(){
  return !/^https?:$/.test(location.protocol) || /^(localhost|127\.|0\.0\.0\.0|\[::1\])/.test(location.hostname);
}
function _shareUrl(){
  const base = _isLocalHost() ? (window.__SITE_URL__ || location.origin) : location.origin;
  return base.replace(/\/$/, '') + '/?t=' + encodeURIComponent(CUR.ticker);
}
function _isMobile(){
  return window.matchMedia && window.matchMedia('(pointer:coarse)').matches;
}

function shareResult(){
  if(!CUR){ showToast('먼저 종목을 분석해 주세요.'); return; }
  const url = _shareUrl();
  // 링크를 화면에도 보여준다 — 복사가 막힌 환경에서도 눈으로 확인하고 직접 복사할 수 있게.
  const box = document.getElementById('shareLinkBox');
  document.getElementById('shareLinkInput').value = url;
  document.getElementById('shareLinkOpen').href = url;
  box.classList.add('show');
  if(!url){ showToast('⚠ 공유할 주소가 없습니다.'); return; }
  // 🐛 [v119] 휴대폰에서만 기기 공유 화면(카카오톡 등)을 띄운다. PC(윈도우 크롬·엣지)에도
  // navigator.share가 있어서 예전엔 윈도우 공유창이 떠 "링크가 안 만들어진다"고 느껴졌다.
  if(_isMobile() && navigator.share){
    navigator.share({ title: '종목분석 미니', text: CUR.name + '(' + CUR.ticker + ') 분석 결과', url: url })
      .catch(()=>{});
    return;
  }
  showToast(_copyText(url)
    ? '🔗 링크를 복사했어요. 카톡·블로그에 붙여넣어 공유하세요.'
    : '🔗 아래 칸의 링크를 선택해서 복사해 주세요.');
}

function copyShareLink(){
  const inp = document.getElementById('shareLinkInput');
  inp.select();
  showToast(_copyText(inp.value) ? '📋 링크를 복사했어요.' : '링크를 길게 눌러(또는 Ctrl+C) 복사해 주세요.');
}

// html2canvas는 이 버튼을 실제로 누를 때만 CDN에서 불러온다(평소 페이지 로딩 속도에
// 영향을 주지 않기 위함 — "이미지 저장"을 한 번도 안 누르면 아예 다운로드되지 않는다).
function _ensureHtml2Canvas(cb){
  if(window.html2canvas){ cb(); return; }
  const s = document.createElement('script');
  s.src = 'https://cdn.jsdelivr.net/npm/html2canvas@1.4.1/dist/html2canvas.min.js';
  s.onload = cb;
  s.onerror = () => showToast('⚠ 이미지 생성 라이브러리를 불러오지 못했습니다. 네트워크를 확인해 주세요.');
  document.body.appendChild(s);
}

function shareResultImage(){
  if(!CUR){ showToast('먼저 종목을 분석해 주세요.'); return; }
  showToast('🖼️ 이미지를 만드는 중...');
  _ensureHtml2Canvas(function(){
    // 결과 카드는 화면 폭만큼 넓어서 그대로 찍으면 오른쪽이 텅 빈 가로로 긴 그림이 된다.
    // 찍는 순간에만 카드 폭을 좁혀(단톡방·SNS에서 보기 좋은 크기) 찍고 곧바로 되돌린다.
    const el = document.getElementById('shareCard');
    const prevWidth = el.style.width;
    el.style.width = '420px';
    html2canvas(el, { backgroundColor: '#ffffff', scale: 2 }).then(canvas=>{
      const a = document.createElement('a');
      a.href = canvas.toDataURL('image/png');
      a.download = String(CUR.name).replace(/[\\/:*?"<>|\s]+/g, '_') + '_' + CUR.ticker + '_분석결과.png';
      a.click();
      showToast('🖼️ 이미지가 저장되었습니다.');
    }).catch(()=>showToast('⚠ 이미지 생성 중 오류가 발생했습니다.'))
      .finally(()=>{ el.style.width = prevWidth; });
  });
}

// ── 💰 [v119] 애드센스 — 화면에 실제로 보이는 광고 자리만 채운다(숨겨진 자리에 넣으면 오류) ──
function pushAds(root){
  if(!window.__ADS__) return;
  (root || document).querySelectorAll('ins.adsbygoogle:not([data-pushed])').forEach(el=>{
    if(el.offsetWidth > 0){
      try{ (window.adsbygoogle = window.adsbygoogle || []).push({}); el.setAttribute('data-pushed', '1'); }catch(e){}
    }
  });
}

// ── 📄 [v119] 전체 리포트 PDF ──────────────────────────────────
//   결과 화면을 복사해 PDF용으로 정리(버튼·입력칸·광고 제외)한 뒤 그림으로 찍어 A4에 나눠 담는다.
//   카드가 페이지 경계에서 잘리지 않도록 카드 사이에서 페이지를 나누고, 모든 페이지 위·아래에
//   chostock.kr과 제작자 블로그 배너를 넣는다(배너는 PDF 안에서 눌러도 해당 사이트로 이동).
const LIB_JSPDF = 'https://cdn.jsdelivr.net/npm/jspdf@2.5.1/dist/jspdf.umd.min.js';
function _loadScript(src){
  return new Promise((resolve, reject)=>{
    if(document.querySelector('script[data-lib="' + src + '"]')){ resolve(); return; }
    const sc = document.createElement('script');
    sc.src = src; sc.setAttribute('data-lib', src);
    sc.onload = ()=>resolve(); sc.onerror = ()=>reject(new Error('load ' + src));
    document.body.appendChild(sc);
  });
}
function _pdfBanner(kind){
  const brand = window.__BRAND_LABEL__ || location.host;
  const blog = (window.__BLOG_URL__ || '').replace(/^https?:\/\//, '');
  const el = document.createElement('div');
  el.className = 'pdfBanner ' + kind;
  el.innerHTML = kind === 'head'
    ? '<div class="bL">📈 종목분석 미니 · ' + _escHtml(brand) + '<small>주식 초보도 쉽게 보는 무료 종목분석 — 모르면 물어보고, 알면 투자하세요</small></div>'
      + '<div class="bR">✍️ 제작자 블로그 · 상세 분석 의뢰<small>' + _escHtml(blog) + '</small></div>'
    : '<div class="bL">✍️ 더 깊은 종목 분석은 제작자 블로그에서 → ' + _escHtml(blog) + '</div>'
      + '<div class="bR">📈 다른 종목도 무료로<small>' + _escHtml(brand) + '</small></div>';
  document.body.appendChild(el);
  return el;
}
function _buildReportDom(){
  const src = document.getElementById('result');
  const w = Math.max(860, Math.min(src.offsetWidth || 860, 1000));
  const wrap = document.createElement('div');
  wrap.className = 'pdfReport';
  wrap.style.width = w + 'px';
  const now = new Date();
  const made = now.getFullYear() + '.' + String(now.getMonth() + 1).padStart(2, '0') + '.' + String(now.getDate()).padStart(2, '0');
  wrap.innerHTML = '<div class="pdfTitleBox"><div class="pdfTitle">' + _escHtml(CUR.name) + '(' + _escHtml(CUR.ticker) + ') 종목분석 리포트</div>'
    + '<div class="pdfSub">' + _escHtml(CUR.market || '') + (CUR.as_of ? ' · 데이터 기준 ' + _escHtml(CUR.as_of) : '') + ' · 작성 ' + made + '</div></div>';
  const clone = src.cloneNode(true);
  clone.style.display = 'block';
  clone.classList.remove('dim');
  clone.querySelectorAll('button, textarea, .aiBtnRow, .aiHint, .shareLinkBox, .adSlot, .pasteHint, .termsLink, .voteCard, .finTabs, script')
    .forEach(el=>el.remove());
  // AI 답변이 없으면 빈 AI 카드는 빼고, 있으면 제목을 리포트용으로 바꾼다.
  clone.querySelectorAll('.card').forEach(card=>{
    const ai = card.querySelector('.aiResult');
    if(!ai) return;
    if(!ai.classList.contains('show')) card.remove();
    else { const h = card.querySelector('h3'); if(h) h.textContent = '🤖 AI 종합 분석'; }
  });
  clone.querySelectorAll('[id]').forEach(el=>el.removeAttribute('id'));
  wrap.appendChild(clone);
  document.body.appendChild(wrap);
  return wrap;
}
// 페이지를 카드 사이에서 나누기 위한 "자를 수 있는 위치" 목록(px, 리포트 기준)
function _breakPoints(wrap){
  const base = wrap.getBoundingClientRect().top;
  const pts = new Set([0]);
  wrap.querySelectorAll('.pdfTitleBox, #result > *, .pdfReport > div > *, .card, .riskBanner, .ctaBanner, .tipBanner, .footNote').forEach(el=>{
    const r = el.getBoundingClientRect();
    if(r.height > 0) pts.add(Math.round(r.bottom - base));
  });
  return Array.from(pts).sort((a, b)=>a - b);
}

let _pdfBusy = false;
async function makePdfReport(){
  if(!CUR){ showToast('먼저 종목을 분석해 주세요.'); return; }
  if(_pdfBusy) return;
  _pdfBusy = true;
  showToast('📄 PDF 리포트를 만드는 중이에요… (5~15초)');
  let wrap = null, head = null, foot = null;
  try{
    if(!window.html2canvas) await _loadScript('https://cdn.jsdelivr.net/npm/html2canvas@1.4.1/dist/html2canvas.min.js');
    await _loadScript(LIB_JSPDF);
    wrap = _buildReportDom(); head = _pdfBanner('head'); foot = _pdfBanner('foot');
    await new Promise(r=>setTimeout(r, 80));  // 폰트·레이아웃 반영 대기
    const W = wrap.offsetWidth, H = wrap.scrollHeight;
    const scale = Math.max(1, Math.min(2, Math.sqrt(15e6 / (W * H))));  // 휴대폰 캔버스 한도(약 1600만 화소) 고려
    const [page, hc, fc] = await Promise.all([
      html2canvas(wrap, { scale: scale, backgroundColor: '#ffffff', useCORS: true, windowWidth: W }),
      html2canvas(head, { scale: 2, backgroundColor: null }),
      html2canvas(foot, { scale: 2, backgroundColor: null }),
    ]);
    const { jsPDF } = window.jspdf;
    const pdf = new jsPDF({ unit: 'mm', format: 'a4', orientation: 'portrait' });
    const PW = pdf.internal.pageSize.getWidth(), PH = pdf.internal.pageSize.getHeight();
    const M = 10, contentW = PW - M * 2;
    const headH = contentW * hc.height / hc.width, footH = contentW * fc.height / fc.width;
    const topY = 5 + headH + 5, bottomY = PH - 5 - footH - 4;
    const pageHpx = (bottomY - topY) * W / contentW;             // 한 페이지에 들어가는 리포트 높이(px)
    const pts = _breakPoints(wrap);
    const slices = [];
    let y = 0;
    while(y < H - 2){
      let end = Math.min(H, y + pageHpx);
      if(end < H){
        const cand = pts.filter(p=>p > y + pageHpx * 0.45 && p <= y + pageHpx);
        if(cand.length) end = cand[cand.length - 1];               // 카드 경계에서 자르기
      }
      slices.push([y, end]); y = end;
    }
    const headImg = hc.toDataURL('image/png'), footImg = fc.toDataURL('image/png');
    const brandUrl = window.__BRAND_URL__ || location.origin, blogUrl = window.__BLOG_URL__ || brandUrl;
    slices.forEach(([y0, y1], i)=>{
      if(i > 0) pdf.addPage();
      const cut = document.createElement('canvas');
      cut.width = page.width; cut.height = Math.max(1, Math.round((y1 - y0) * scale));
      const ctx = cut.getContext('2d');
      ctx.fillStyle = '#ffffff'; ctx.fillRect(0, 0, cut.width, cut.height);
      ctx.drawImage(page, 0, Math.round(y0 * scale), page.width, cut.height, 0, 0, cut.width, cut.height);
      pdf.addImage(cut.toDataURL('image/jpeg', 0.9), 'JPEG', M, topY, contentW, (y1 - y0) * contentW / W);
      // 위: 왼쪽 절반 = 사이트, 오른쪽 절반 = 블로그 / 아래: 왼쪽 = 블로그, 오른쪽 = 사이트
      pdf.addImage(headImg, 'PNG', M, 5, contentW, headH);
      pdf.link(M, 5, contentW * 0.62, headH, { url: brandUrl });
      pdf.link(M + contentW * 0.62, 5, contentW * 0.38, headH, { url: blogUrl });
      pdf.addImage(footImg, 'PNG', M, PH - 5 - footH, contentW, footH);
      pdf.link(M, PH - 5 - footH, contentW * 0.65, footH, { url: blogUrl });
      pdf.link(M + contentW * 0.65, PH - 5 - footH, contentW * 0.35, footH, { url: brandUrl });
      pdf.setFontSize(8); pdf.setTextColor(140);
      pdf.text((i + 1) + ' / ' + slices.length, PW - M, PH - 5 - footH - 1.5, { align: 'right' });
    });
    pdf.save(String(CUR.name).replace(/[\\/:*?"<>|\s]+/g, '_') + '_' + CUR.ticker + '_종목분석리포트.pdf');
    showToast('📄 PDF 리포트를 저장했어요.');
  }catch(e){
    console.error('[PDF]', e);
    showToast('⚠ PDF를 만들지 못했어요. 네트워크를 확인하고 다시 시도해 주세요.');
  }finally{
    [wrap, head, foot].forEach(el=>{ if(el && el.parentNode) el.parentNode.removeChild(el); });
    _pdfBusy = false;
  }
}

// /api/ai-prompt와 같은 패턴(POST + CUR) — 서버가 네이버를 다시 조회하지 않게 한다.
function _fetchBlogDraft(){
  return fetch('/api/blog-export/' + CUR.ticker, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(CUR),
  }).then(r=>r.json());
}

function toggleBlogBox(){
  if(!CUR){ showToast('먼저 종목을 분석해 주세요.'); return; }
  const box = document.getElementById('blogDraftBox');
  if(box.style.display === 'none'){
    if(!box.value){
      _fetchBlogDraft().then(d=>{
        if(d.error){ showToast('⚠ ' + d.error); return; }
        box.value = d.draft;
        box.style.display = 'block';
        box.focus(); box.select();
        _copyText(d.draft);
        showToast('📝 블로그 글이 복사되었습니다. 원하는 블로그에 붙여넣으세요.');
      }).catch(()=>showToast('⚠ 블로그 글 생성 중 오류가 발생했습니다.'));
    } else {
      box.style.display = 'block';
    }
  } else {
    box.style.display = 'none';
  }
}

function _escHtml(s){
  return String(s==null?'':s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}

// 🚀 [v105] "글씨가 작아 잘 안 보인다 — 가독성 높게" — 줄 단위로 처리해서 섹션 제목
//   ([1. 제목] 형식이나 마크다운 ## 제목 모두 인식) · 굵게 · 글머리 기호를 각각 알맞은
//   스타일로 렌더링한다. 폰트 크기·줄간격도 함께 키워서 눈에 잘 들어오게 했다.
function renderAiResult(){
  const raw = document.getElementById('aiPasteBox').value.trim();
  const box = document.getElementById('aiResult');
  if(!raw){ box.classList.remove('show'); box.innerHTML = ''; return; }

  const lines = raw.split('\n');
  const parts = [];
  lines.forEach(function(line){
    const t = line.trim();
    if(!t){ parts.push('<div style="height:8px;"></div>'); return; }

    // 섹션 제목: "[1. 제목]" / "[제목]" 또는 마크다운 "# 제목" ~ "### 제목"
    const headerMatch = t.match(/^\[(.+)\]$/) || t.match(/^#{1,3}\s*(.+)$/);
    if(headerMatch){
      parts.push('<div class="aiSection">' + _escHtml(headerMatch[1]).replace(/\*\*(.+?)\*\*/g, '$1') + '</div>');
      return;
    }

    // 글머리 기호: "- 텍스트" 또는 "• 텍스트"
    const bulletMatch = t.match(/^[-•]\s+(.*)$/);
    const content = bulletMatch ? bulletMatch[1] : t;
    const html = _escHtml(content).replace(/\*\*(.+?)\*\*/g, '<b>$1</b>');

    if(bulletMatch){
      parts.push('<span class="aiBullet">' + html + '</span>');
    } else {
      parts.push('<p>' + html + '</p>');
    }
  });

  box.innerHTML = parts.join('');
  box.classList.add('show');
  box.scrollIntoView({behavior:'smooth', block:'nearest'});

  // 🐛 [v108] "상단 기업개요를 AI 분석을 통해 끌어오도록" — 네이버에서 개요 문단을
  // 못 가져왔을 때(overview_source가 naver가 아닐 때), AI 응답의 "[1. 기업 소개 및
  // 사업 개요]" 섹션을 찾아 상단 카드에 채운다. 네이버에서 이미 실제 개요를 가져온
  // 경우(overview_source==='naver')는 그 내용을 유지한다(네이버 우선 원칙 그대로 준수).
  if(CUR && CUR.details && CUR.details.overview_source !== 'naver'){
    const secMatch = raw.match(/\[1\.[^\]]*(?:기업|사업)[^\]]*\]([\s\S]*?)(?=\n\s*\[\d+\.|\n\s*\[[가-힣A-Za-z]|$)/);
    if(secMatch && secMatch[1].trim()){
      const aiOverview = secMatch[1].trim().replace(/\*\*(.+?)\*\*/g, '$1');
      document.getElementById('overviewCard').style.display = 'block';
      document.getElementById('overviewText').textContent = aiOverview;
      const badge = document.getElementById('overviewSourceBadge');
      if(badge) badge.textContent = '🤖 AI 분석 기반';
    }
  }
}

// 🚀 [v1.2] "복사→붙여넣기 하면 자동으로 보기 좋게 표시" — 버튼을 누르지 않아도
//   붙여넣는(또는 입력하는) 즉시 자동으로 정리해서 보여준다. 붙여넣기 직후 렌더링하도록
//   약간의 지연(paste 이벤트가 실제로 textarea 값에 반영된 뒤 읽도록)을 둔다.
const aiPasteBoxEl = document.getElementById('aiPasteBox');
let _aiRenderTimer = null;
function _scheduleAiRender(){
  clearTimeout(_aiRenderTimer);
  _aiRenderTimer = setTimeout(renderAiResult, 120);
}
aiPasteBoxEl.addEventListener('paste', _scheduleAiRender);
aiPasteBoxEl.addEventListener('input', _scheduleAiRender);
</script>
</body>
</html>
"""


# ══════════════════════════════════════════════════════════════
# 도움말(증권용어 해설) 페이지 — [v113] 신설
# ══════════════════════════════════════════════════════════════
HELP_HTML = r"""
<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>도움말 · 증권용어 해설 — 종목분석 미니</title>
<style>
  :root{
    --navy:#10203a; --muted:#8993a4; --text:#1c2430; --line:#e8ecf3;
    --good:#16a34a; --bad:#dc2626; --warn:#a16207; --bg:#f4f6fb;
  }
  *{box-sizing:border-box;}
  body{
    margin:0; font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","Noto Sans KR",sans-serif;
    background:var(--bg); color:var(--text); line-height:1.6;
  }
  .topbar{
    background:var(--navy); color:#fff; padding:16px 24px; display:flex; align-items:center;
    justify-content:space-between; flex-wrap:wrap; gap:10px; position:sticky; top:0; z-index:10;
  }
  .topbar .brand{font-size:16px; font-weight:800;}
  .topbar .verTag{font-size:11px; font-weight:700; opacity:.75; margin-left:6px;}
  .topbar a.back{color:#fff; font-size:12.5px; text-decoration:none; background:rgba(255,255,255,.14);
    padding:7px 14px; border-radius:20px; font-weight:700;}
  .topbar a.back:hover{background:rgba(255,255,255,.24);}
  .wrap{max-width:840px; margin:0 auto; padding:22px 18px 60px;}
  .staleBanner{
    background:#fff7ed; border:1px solid #fdba74; color:#9a3412; border-radius:12px;
    padding:14px 18px; font-size:12.5px; font-weight:600; margin-bottom:20px; line-height:1.7;
  }
  .intro{
    background:#fff; border:1px solid var(--line); border-radius:14px; padding:20px 22px;
    margin-bottom:18px; font-size:13.5px; color:#475569;
  }
  .intro b{color:var(--navy);}
  .toc{
    background:#fff; border:1px solid var(--line); border-radius:14px; padding:16px 20px;
    margin-bottom:22px;
  }
  .toc h2{font-size:13px; margin:0 0 10px; color:var(--muted);}
  .toc ul{margin:0; padding-left:18px; columns:2; font-size:13px;}
  .toc li{margin-bottom:6px;}
  .toc a{color:var(--navy); text-decoration:none; font-weight:600;}
  .toc a:hover{text-decoration:underline;}
  section.card{
    background:#fff; border:1px solid var(--line); border-radius:14px; padding:22px 24px;
    margin-bottom:16px; scroll-margin-top:76px;
  }
  section.card h2{font-size:16px; margin:0 0 14px; color:var(--navy); display:flex; align-items:center; gap:8px;}
  dl.termList{margin:0;}
  dl.termList dt{font-size:13.5px; font-weight:800; color:var(--navy); margin-top:14px;}
  dl.termList dt:first-child{margin-top:0;}
  dl.termList dd{margin:5px 0 0; font-size:13px; color:#475569; line-height:1.75;}
  dl.termList dd .ex{display:block; margin-top:4px; font-size:12px; color:var(--muted); background:#f8f9fc; border-radius:8px; padding:8px 10px;}
  .back-to-top{display:inline-block; margin-top:8px; font-size:11.5px; color:var(--muted); text-decoration:none;}
  .back-to-top:hover{text-decoration:underline;}
  .footNote{font-size:11.5px; color:var(--muted); text-align:center; margin-top:28px;}
</style>
</head>
<body>

<div class="topbar" id="top">
  <div class="brand">❓ 도움말 · 증권용어 해설 <span class="verTag">앱 {{ app_version }} · 도움말 기준 {{ asof }}</span></div>
  <a class="back" href="/">← 분석 화면으로 돌아가기</a>
</div>

<div class="wrap">

  {% if stale %}
  <div class="staleBanner">
    ⚠️ 이 도움말은 <b>{{ asof }}</b> 시점 화면을 기준으로 작성되었고, 현재 앱 버전은 <b>{{ app_version }}</b>입니다.
    그 사이 화면 구성이나 용어가 바뀌었다면 아래 설명이 실제 화면과 차이가 있을 수 있습니다.
    최신 설명이 필요하면 제작자 블로그나 업데이트 공지를 확인해 주세요.
  </div>
  {% endif %}

  <div class="intro">
    이 페이지는 <b>종목분석 미니</b> 화면에 나오는 증권 용어를 초보자 기준으로 풀어 설명합니다.
    투자 판단에 참고할 수는 있지만, 이 프로그램의 어떤 지표·설명도 매수·매도 추천이 아니며
    투자 결과에 대한 책임은 투자자 본인에게 있습니다.
  </div>

  <div class="toc">
    <h2>목차</h2>
    <ul>
      <li><a href="#sec-trend">① 추세·기술적 지표</a></li>
      <li><a href="#sec-chart">② 주가 차트(캔들·이동평균·구름·매물대)</a></li>
      <li><a href="#sec-value">③ 밸류에이션(PER·PBR 등)</a></li>
      <li><a href="#sec-peer">④ 동일업종 비교·컨센서스</a></li>
      <li><a href="#sec-risk">⑤ 상장폐지 위험 경고</a></li>
      <li><a href="#sec-ai">⑥ AI 분석(수동 모드) 사용법</a></li>
      <li><a href="#sec-share">⑦ 재무·뉴스·매력도 체크·공유·PDF</a></li>
    </ul>
  </div>

  <section class="card" id="sec-trend">
    <h2>① 추세·기술적 지표</h2>
    <dl class="termList">
      <dt>RSI(14)</dt>
      <dd>최근 14일간 가격이 오른 폭과 내린 폭의 비율로 매수·매도 힘의 균형을 가늠하는 지표(0~100).
        <span class="ex">70 이상 = 과매수(단기적으로 많이 오름, 조정 가능성) · 30 이하 = 과매도(단기적으로 많이 내림, 반등 가능성). 40~65는 중립적인 구간으로 봅니다.</span>
      </dd>
      <dt>이동평균 배열</dt>
      <dd>5일·20일·60일 이동평균선(최근 N일 종가의 평균을 이어 그린 선)이 화면에 정렬된 순서.
        <span class="ex">정배열(5일선 > 20일선 > 60일선) = 상승 추세 · 역배열(반대 순서) = 하락 추세로 해석합니다.</span>
      </dd>
      <dt>거래량 배수</dt>
      <dd>오늘 거래량이 최근 20일 평균 거래량의 몇 배인지 나타내는 값.
        <span class="ex">2배 이상이면 평소보다 관심(매수든 매도든)이 크게 쏠렸다는 뜻으로, 추세 전환의 신호로 참고됩니다.</span>
      </dd>
      <dt>52주 위치</dt>
      <dd>최근 52주(1년)의 최저가~최고가 구간에서 현재가가 몇 %에 있는지(0%=52주 최저가, 100%=52주 최고가).
        <span class="ex">위치가 낮다고 반드시 "저평가"는 아닙니다 — 실적 악화 등으로 계속 눌려 있을 수도 있으니 다른 지표와 함께 봐야 합니다.</span>
      </dd>
      <dt>20일선 이격도</dt>
      <dd>현재가가 20일 이동평균선보다 얼마나(%) 떨어져 있는지.
        <span class="ex">이격도가 너무 크면(양수든 음수든) 평균 쪽으로 되돌아오려는 힘(평균회귀)이 작용할 수 있다고 해석하는 경우가 많습니다.</span>
      </dd>
      <dt>5일/20일 등락률</dt>
      <dd>최근 5거래일, 20거래일 동안의 누적 등락률로, 단기·중기 추세의 방향과 속도를 함께 보여줍니다.</dd>
      <dt>볼린저밴드 스퀴즈(변동성 압축)</dt>
      <dd>주가 변동폭이 평소보다 눈에 띄게 좁아진 상태.
        <span class="ex">변동성이 압축된 뒤에는 위든 아래든 방향성 있는 큰 움직임(돌파)이 나올 가능성이 커진다고 보는 경우가 많지만, 방향은 미리 알 수 없습니다.</span>
      </dd>
    </dl>
    <a class="back-to-top" href="#top">↑ 목차로</a>
  </section>

  <section class="card" id="sec-chart">
    <h2>② 주가 차트(캔들·이동평균·구름·매물대)</h2>
    <dl class="termList">
      <dt>캔들차트</dt>
      <dd>하루의 시가·고가·저가·종가를 막대 하나로 표현한 차트. 종가가 시가보다 높으면 보통 빨간색(양봉), 낮으면 파란색(음봉)으로 표시됩니다.</dd>
      <dt>이동평균선(MA5/MA20/MA60)</dt>
      <dd>최근 5일·20일·60일 종가의 평균을 이어 그린 선으로, 단기·중기·장기 추세의 방향을 부드럽게 보여줍니다.</dd>
      <dt>일목균형표 구름(선행스팬 A/B)</dt>
      <dd>전환선(최근 9일 고가·저가의 중간값)과 기준선(최근 26일 고가·저가의 중간값)을 이용해 계산한 두 개의 선(선행스팬 A·B)을
        <b>26일 앞으로</b> 미리 옮겨 그린 뒤, 그 사이를 색칠해 띠(구름) 모양으로 표시한 것입니다.
        <span class="ex">주가가 구름 위에 있으면 상승 추세, 구름 아래에 있으면 하락 추세로 보는 경우가 많고, 구름 자체가 두꺼울수록
        그 구간이 강한 지지/저항대로 작용할 수 있다고 해석됩니다. 구름이 미래 쪽으로도 그려지는 이유는 26일 뒤로 미리 투영된 값이기 때문입니다.</span>
      </dd>
      <dt>매물대(Volume Profile) · POC · VAL · VAH</dt>
      <dd>최근 60거래일 동안 어떤 가격대에서 거래(매물)가 가장 많이 쌓였는지를 계산한 것입니다.
        <span class="ex">
        POC(Point of Control, 최대 매물 기준가) = 거래가 가장 많이 몰린 가격대.<br>
        VAL(Value Area Low, 가치 영역 하단) = 전체 거래의 대부분(통상 70%)이 몰린 구간의 아래쪽 경계 — 흔히 지지선으로 참고.<br>
        VAH(Value Area High, 가치 영역 상단) = 같은 구간의 위쪽 경계 — 흔히 저항선으로 참고.<br>
        매물이 많이 쌓인 가격대는 그만큼 그 가격에 사고판 사람이 많다는 뜻이라, 주가가 다시 그 근처로 오면 지지(하락을 막는 힘) 또는
        저항(상승을 막는 힘)으로 작용하는 경우가 많다고 해석됩니다. 단, 미래를 보장하는 것은 아닙니다.</span>
      </dd>
    </dl>
    <a class="back-to-top" href="#top">↑ 목차로</a>
  </section>

  <section class="card" id="sec-value">
    <h2>③ 밸류에이션(PER·PBR 등)</h2>
    <dl class="termList">
      <dt>PER(주가수익비율)</dt>
      <dd>주가 ÷ 주당순이익(EPS). 회사가 벌어들이는 이익에 비해 주가가 몇 배인지를 나타냅니다.
        <span class="ex">낮을수록 이익 대비 저평가라고 해석하는 경우가 많지만, 업종별로 평균 수준이 크게 다르므로 반드시 업종 평균과 비교해야 합니다.</span>
      </dd>
      <dt>PBR(주가순자산비율)</dt>
      <dd>주가 ÷ 주당순자산(BPS). 회사의 장부상 자산 가치에 비해 주가가 몇 배인지를 나타냅니다. 1배 미만이면 이론상 장부가치보다 싸게 거래된다는 뜻입니다.</dd>
      <dt>EPS(주당순이익) · BPS(주당순자산)</dt>
      <dd>EPS는 1주당 벌어들인 순이익, BPS는 1주당 장부상 순자산(자본)을 나타내는 값으로, PER·PBR 계산의 기준이 됩니다.</dd>
      <dt>배당수익률</dt>
      <dd>1주당 연간 배당금 ÷ 현재 주가. 주가 대비 배당으로 얻는 수익 비율을 뜻하며, 배당은 회사 사정에 따라 변경·중단될 수 있습니다.</dd>
      <dt>시가총액</dt>
      <dd>현재 주가 × 총 발행주식수. 회사 전체의 시장 가치를 나타내는 지표입니다.</dd>
    </dl>
    <a class="back-to-top" href="#top">↑ 목차로</a>
  </section>

  <section class="card" id="sec-peer">
    <h2>④ 동일업종 비교·컨센서스</h2>
    <dl class="termList">
      <dt>동일업종 관련 종목</dt>
      <dd>같은 업종으로 분류된 다른 종목들의 현재가·등락률을 보여줍니다. 이 화면에서는 가격·등락률만 제공되며 PER/PBR은 데이터 출처 한계로 표시되지 않습니다.</dd>
      <dt>애널리스트 컨센서스(목표주가)</dt>
      <dd>증권사 애널리스트들이 제시한 목표주가의 평균치입니다.
        <span class="ex">어디까지나 증권사들의 평균 "전망"일 뿐 확정된 미래 주가가 아니며, 실제 주가와 크게 다를 수 있습니다. 투자의견 점수는 보통 1(강력매수)~5(매도)로 표시되며 낮을수록 긍정적인 의견입니다.</span>
      </dd>
    </dl>
    <a class="back-to-top" href="#top">↑ 목차로</a>
  </section>

  <section class="card" id="sec-risk">
    <h2>⑤ 상장폐지 위험 경고</h2>
    <dl class="termList">
      <dt>상장폐지 위험 배지(🚨/⚠️)</dt>
      <dd>거래정지·관리종목 지정 사유가 될 수 있는 공개 정보(거래상태, 동전주 여부, 시가총액 기준 미달 가능성 등)를 바탕으로 한
        참고용 경고입니다.
        <span class="ex">이 경고는 공식적인 상장폐지 결정이 아니라 정황상 위험 신호를 미리 알려주는 것뿐이므로, 반드시 KRX·DART 공시를 통해
        직접 확인해야 합니다.</span>
      </dd>
    </dl>
    <a class="back-to-top" href="#top">↑ 목차로</a>
  </section>

  <section class="card" id="sec-ai">
    <h2>⑥ AI 분석(수동 모드) 사용법</h2>
    <dl class="termList">
      <dt>왜 "수동 모드"인가요?</dt>
      <dd>이 프로그램은 유료 AI API 키 없이 누구나 무료로 쓸 수 있도록, AI를 직접 호출하지 않고 "분석에 필요한 프롬프트(질문 내용)"만
        자동으로 만들어 드립니다.</dd>
      <dt>사용 순서</dt>
      <dd>
        <span class="ex">
        1. 종목을 검색해 분석 화면을 엽니다.<br>
        (v121부터 프롬프트에 최근 3년·분기 재무 추이와 최근 2주 뉴스 제목이 함께 들어가, AI가 실적과 이슈까지 분석합니다.)<br>
        2. "AI 분석(수동 모드)" 카드에서 원하는 AI(제미나이·챗GPT·클로드) 버튼을 누르면 그 순간 분석 프롬프트가 이미 복사되어 있고, 안내창이 뜹니다.<br>
        3. 안내창의 [열기]를 누르면 AI 사이트가 새 창으로 열립니다. 입력칸에 Ctrl+V(휴대폰은 길게 눌러 붙여넣기) 후 전송합니다.<br>
        4. AI 답변이 끝나면 답변 아래 복사 버튼을 누르고 이 화면으로 돌아오세요. 답변이 AI 분석 칸에 자동으로 들어가 보기 좋게 정리됩니다.<br>
        5. 자동으로 안 들어오면(브라우저가 클립보드 읽기를 막는 경우) [📥 복사한 답변 붙여넣기]를 누르거나 칸을 누르고 Ctrl+V 하세요.</span>
      </dd>
      <dt>주의할 점</dt>
      <dd>이 AI 리포트는 외국인·기관 수급과 공시 원문을 포함하지 않고, 뉴스는 제목만 참고합니다(공개판 한계). 투자 결정 전 반드시
        별도로 확인하시고, 리포트 내용은 투자 추천이 아닌 참고 의견입니다.</dd>
    </dl>
    <a class="back-to-top" href="#top">↑ 목차로</a>
  </section>

  <section class="card" id="sec-share">
    <h2>⑦ 재무·뉴스·매력도 체크·공유·PDF</h2>
    <dl class="termList">
      <dt>🔗 링크 공유</dt>
      <dd>지금 보고 있는 종목으로 바로 열리는 링크를 만듭니다. 휴대폰에서는 공유 화면이 뜨고, PC에서는 링크가 복사됩니다.
        받은 사람이 링크를 열면 같은 종목 분석 화면이 곧바로 나타납니다.</dd>
      <dt>🖼️ 이미지로 저장</dt>
      <dd>종목명·현재가가 담긴 결과 카드를 그림 파일(PNG)로 저장합니다. 단톡방이나 SNS에 올리기 좋습니다.</dd>
      <dt>📝 블로그 내보내기</dt>
      <dd>주요 수치(현재가·PER·PBR·RSI·매물대 등)를 정리한 글을 만들어 자동으로 복사합니다. AI를 거치지 않으므로 바로 만들어지며,
        블로그에 붙여넣은 뒤 본인 의견을 덧붙여 쓰시면 됩니다.</dd>
      <dt>📑 재무 정보</dt>
      <dd>최근 3년(연간)과 최근 분기의 매출액·영업이익·순이익·이익률·ROE·부채비율·EPS·배당을 표와 그래프로 보여줍니다.
        노란 칸 (E)는 확정 실적이 아니라 증권사들의 추정치입니다. 매출·이익 아래 작은 숫자는 직전 기간 대비 증감률입니다.</dd>
      <dt>📰 최근 2주 뉴스</dt>
      <dd>네이버 증권이 이 종목 관련으로 분류한 기사 중 최근 14일 이내 것만 보여줍니다. AI 분석 프롬프트에도 제목이 함께 들어갑니다.</dd>
      <dt>💡 매력도 체크</dt>
      <dd>"사고 싶어요 / 지켜볼래요 / 아직은 아니에요" 중 하나를 누르면 다른 이용자들의 선택과 함께 보여줍니다(최근 30일 기준).
        한 브라우저에서 종목마다 한 표이며, 같은 버튼을 다시 누르면 취소됩니다. 투표 결과는 참고용이며 투자 권유가 아닙니다.
        첫 화면의 "이번 주 매수 관심 TOP"은 최근 7일 동안 '사고 싶어요'를 많이 받은 종목입니다.</dd>
      <dt>🌐 시세 출처</dt>
      <dd>시세는 기본적으로 네이버 증권에서 가져오고, 네이버가 응답하지 않으면 야후 파이낸스에서 대신 가져옵니다.
        야후 시세는 장중에 15~20분 늦을 수 있으며, 가격 아래 "시세 출처"에 표시됩니다. 이때 재무·뉴스 등 네이버 전용 정보는 일부 빠질 수 있습니다.</dd>
      <dt>↺ 초기화</dt>
      <dd>검색어·분석 결과·AI 칸을 모두 비우고 첫 화면으로 돌아갑니다. 최근 본 종목의 [기록 지우기]는 이 브라우저의 조회 기록만 지웁니다.</dd>
      <dt>📄 PDF 리포트</dt>
      <dd>지금 화면의 분석 결과(AI 분석을 붙여넣었다면 그 내용까지)를 A4 PDF 파일로 저장합니다. 인쇄하거나 메신저로 보내기 좋습니다.</dd>
      <dt>🕘 최근 본 종목</dt>
      <dd>첫 화면에 최근 분석한 종목이 표시됩니다. 같은 브라우저라면 새로고침하거나 다음에 다시 와도 남아 있습니다.
        로그인 없이 브라우저에 저장된 무작위 번호로만 구분하며, 이름·이메일 같은 개인정보는 받지 않습니다.
        브라우저 쿠키를 지우면 목록도 초기화됩니다.</dd>
    </dl>
    <a class="back-to-top" href="#top">↑ 목차로</a>
  </section>

  <div class="footNote">이 도움말의 모든 설명은 일반적인 증권 용어 해설이며, 특정 종목에 대한 투자 조언이 아닙니다.</div>

</div>
</body>
</html>
"""


PRIVACY_HTML = r"""
<!DOCTYPE html>
<html lang="ko"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>개인정보처리방침 · 종목분석 미니</title>
<link rel="stylesheet" href="https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.9/dist/web/static/pretendard.css">
<style>
  body{margin:0;background:#f4f6fb;color:#1a2233;font-family:Pretendard,-apple-system,sans-serif;line-height:1.8;}
  .wrap{max-width:760px;margin:0 auto;padding:28px 18px 60px;}
  .card{background:#fff;border:1px solid #e7eaf1;border-radius:16px;padding:22px 24px;margin-bottom:14px;}
  h1{font-size:20px;margin:0 0 4px;color:#10203a;} h2{font-size:15px;margin:0 0 8px;color:#10203a;}
  p,li{font-size:13.5px;} .muted{color:#8993a4;font-size:12px;} a{color:#2563eb;}
</style></head><body><div class="wrap">
  <div class="card"><h1>개인정보처리방침</h1><div class="muted">종목분석 미니({{ site_label }}) · 시행일 2026년 9월 29일</div></div>
  <div class="card"><h2>1. 수집하는 정보</h2><ul>
    <li><b>익명 식별 쿠키(anon_uid)</b> — 처음 방문할 때 브라우저에 저장되는 무작위 문자열입니다. 이름·이메일·전화번호 등 개인을 알아볼 수 있는 정보와 연결되지 않습니다.</li>
    <li><b>조회 기록</b> — 분석한 종목코드·종목명·시장·조회 시각을 위 익명 식별값과 함께 저장합니다.</li>
    <li><b>매력도 투표</b> — 종목별로 누른 선택(사고 싶어요/지켜볼래요/아직은)과 시각을 익명 식별값과 함께 저장하며, 다른 이용자에게는 합계만 보여줍니다.</li>
    <li><b>브라우저 저장소</b> — 이용 안내 동의 여부, 안내창 다시 보지 않기 설정을 이용자의 브라우저에만 저장합니다(서버로 전송하지 않음).</li>
  </ul><p>회원가입이 없으며, 이름·이메일·연락처 등은 수집하지 않습니다.</p></div>
  <div class="card"><h2>2. 이용 목적</h2><ul>
    <li>종목별 매력도 투표 합계와 "이번 주 매수 관심 TOP" 표시</li>
    <li>"최근 본 종목" 목록 표시(같은 브라우저로 다시 방문했을 때)</li>
    <li>누적 이용 통계(예: 몇 명이 몇 건을 분석했는지) 표시와 서비스 개선</li>
  </ul></div>
  <div class="card"><h2>3. 보관 기간과 삭제</h2><p>익명 식별 쿠키는 최대 2년간 유지되며, 브라우저 설정에서 쿠키를 삭제하면 즉시 사라지고 이후 기록은 이전 기록과 연결되지 않습니다. 조회 기록은 서비스 운영 기간 동안 보관합니다.</p></div>
  <div class="card"><h2>4. 광고와 제3자 쿠키</h2><p>이 사이트는 Google 애드센스 광고를 게재할 수 있습니다. Google을 포함한 제3자 공급업체는 쿠키를 사용하여 이용자의 이 사이트 또는 다른 사이트 방문 기록을 바탕으로 광고를 게재합니다. Google은 광고 쿠키를 사용해 이용자에게 맞춤 광고를 보여줄 수 있으며, 이용자는 <a href="https://adssettings.google.com" target="_blank" rel="noopener">Google 광고 설정</a>에서 맞춤 광고를 해제할 수 있습니다. 자세한 내용은 <a href="https://policies.google.com/technologies/ads" target="_blank" rel="noopener">Google 광고 정책</a>을 참고하세요.</p></div>
  <div class="card"><h2>5. 제3자 제공</h2><p>수집한 정보를 판매하거나 제3자에게 제공하지 않습니다. 다만 서비스 운영을 위해 호스팅(Render) 서버에 저장됩니다.</p></div>
  <div class="card"><h2>6. 문의</h2><p>개인정보 관련 문의는 <a href="{{ blog_url }}" target="_blank" rel="noopener">제작자 블로그</a>로 남겨 주세요.</p></div>
  <div class="muted" style="text-align:center;"><a href="/">← 종목분석 미니로 돌아가기</a></div>
</div></body></html>
"""


# ══════════════════════════════════════════════════════════════
# 모듈 로드 시 초기화 (⚠️ v114: 웹 배포 대응)
# ══════════════════════════════════════════════════════════════
# gunicorn 같은 운영용 WSGI 서버는 "python 파일.py"처럼 main()을 호출하지 않는다 —
# 그냥 이 모듈을 import한 뒤 아래 `app = Flask(__name__)` 객체를 곧바로 가져다 쓴다
# (예: gunicorn stock_analyzer_mini:app). 그래서 DB 테이블 생성(init_db)과 종목명
# 캐시 구축 스레드 시작은 main() 안이 아니라 반드시 "이 파일이 import되는 시점"인
# 여기서 실행해야 한다 — main() 안에만 두면 gunicorn 배포 시 DB 테이블이 아예
# 생성되지 않아 첫 요청부터 에러가 난다.
# "python 파일.py"로 직접 실행할 때도 동작은 이전과 동일하다 — 어차피 그 실행도
# 내부적으로 이 모듈을 한 번 로드하므로 아래 코드가 (main() 호출보다 먼저) 실행되고,
# 중복 실행되지 않는다.
_WEB_MODE = bool(os.environ.get("PORT"))  # Render/Railway 등 PaaS가 자동 주입하는 포트
                                            # 환경변수 — 있으면 "웹 배포 모드"로 판단한다.

# 🔒 [v118] Render 등 PaaS는 HTTPS를 앞단 프록시에서 처리하고 앱에는 http로 넘겨준다.
# 이걸 알려주지 않으면 블로그 글에 들어가는 "직접 분석해보기" 링크가 http://로 만들어진다.
# X-Forwarded-Proto/Host 헤더를 신뢰하도록 웹 배포 모드에서만 ProxyFix를 씌운다.
if _WEB_MODE:
    from werkzeug.middleware.proxy_fix import ProxyFix
    app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)

init_db()
_ensure_votes_table()    # 💡 [v121] 매력도 투표 테이블
_ensure_history_table()  # ⚠️ [v117] 검색 기록 테이블 준비. [v118] DB가 아직 안 붙어도 부팅은
                         # 계속되고(예외 삼킴), 첫 기록 요청 때 다시 시도한다.
threading.Thread(target=build_ticker_cache, daemon=True).start()
threading.Thread(target=_warm_cache_loop, daemon=True).start()  # ⚡ [v119] 데모·인기 종목 미리 불러오기


# ══════════════════════════════════════════════════════════════
# 실행 진입점
# ══════════════════════════════════════════════════════════════
def _find_free_port(preferred=5055):
    """선호 포트가 이미 사용 중이면 빈 포트를 자동으로 찾는다(다른 프로그램과 충돌 방지)."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind(("127.0.0.1", preferred))
        s.close()
        return preferred
    except OSError:
        s.close()
        s2 = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s2.bind(("127.0.0.1", 0))
        port = s2.getsockname()[1]
        s2.close()
        return port


def _wait_for_server(port, timeout=8.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                return True
        except OSError:
            time.sleep(0.15)
    return False


def main():
    # ⚠️ [v114] init_db()/build_ticker_cache 스레드 시작은 이제 모듈 로드 시점(위
    # "모듈 로드 시 초기화" 섹션)에서 이미 끝났다 — 여기서 다시 실행하지 않는다.

    if _WEB_MODE:
        # 🌐 [v114] 웹 배포 모드 — Render/Railway 등 PaaS가 PORT 환경변수로 알려준
        # 포트에 0.0.0.0으로 바인딩한다. GitHub 자동 업데이트(exe 전용 개념)와
        # pywebview 창 띄우기는 의미가 없으므로 건너뛴다.
        # 참고: gunicorn(Procfile 권장 방식)으로 띄우면 이 main()조차 호출되지 않고
        # gunicorn이 app 객체를 직접 쓴다 — 아래 app.run()은 Procfile 없이
        # "python stock_analyzer_mini.py"를 서버에서 직접 실행하는 경우를 위한 안전망이다.
        port = int(os.environ.get("PORT", 5055))
        print("=" * 60)
        print("  📈 종목분석 미니 (웹 배포 모드)")
        print(f"  0.0.0.0:{port} 에서 대기 중")
        print("=" * 60)
        app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)
        return

    # 🔄 [v108] GitHub 자동 업데이트 — 다른 모든 것(Flask 서버·창 등)보다 먼저 확인한다.
    # 새 버전이 있으면 여기서 프로세스가 종료되고(배치 스크립트가 교체·재실행을 이어받음),
    # 없거나 확인에 실패하면 그대로 아래로 진행해 평소처럼 프로그램이 시작된다.
    # (웹 배포 모드에서는 위에서 이미 return 했으므로 여기 도달하지 않는다.)
    if run_auto_update_check():
        os._exit(0)

    if not FDR_OK:
        print("=" * 60)
        print("⚠ FinanceDataReader가 설치되어 있지 않습니다.")
        print("  아래 명령으로 설치한 뒤 다시 실행해 주세요:")
        print(f'  "{sys.executable}" -m pip install finance-datareader')
        print("=" * 60)
    if not BS4_OK:
        print("⚠ beautifulsoup4가 없어 매출구성 조회가 제한됩니다(PER/PBR 등 핵심 지표는 정상 동작).")
        print(f'  "{sys.executable}" -m pip install beautifulsoup4')

    port = _find_free_port(5055)

    def _run_flask():
        app.run(host="127.0.0.1", port=port, debug=False, use_reloader=False)

    server_thread = threading.Thread(target=_run_flask, daemon=True)
    server_thread.start()
    _wait_for_server(port)

    url = f"http://127.0.0.1:{port}"
    print("=" * 60)
    print("  📈 종목분석 미니")
    print(f"  접속 주소: {url}")
    print("=" * 60)

    try:
        import webview
        try:
            webview.settings["ALLOW_DOWNLOADS"] = True  # [v118] 창 앱에서도 "이미지로 저장"이 되도록
        except Exception:
            pass
        webview.create_window("종목분석 미니", url, width=1180, height=860, min_size=(980, 680))
        webview.start()
    except Exception:
        # pywebview가 없거나 창 생성에 실패하면 기본 브라우저로 연다.
        webbrowser.open(url)
        print("  (창 앱으로 실행하려면: pip install pywebview)")
        print("  Ctrl+C 를 누르면 종료됩니다.")
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            print("\n종료합니다.")


if __name__ == "__main__":
    main()
