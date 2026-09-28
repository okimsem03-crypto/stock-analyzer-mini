# -*- coding: utf-8 -*-
"""
📈 종목분석 미니 (공개판) — v114
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

실행(로컬/데스크톱):  python stock_analyzer_mini.py
실행(웹 서버, 예: Render):  gunicorn stock_analyzer_mini:app --bind 0.0.0.0:$PORT
필요:  pip install flask finance-datareader pandas numpy requests beautifulsoup4
       (pip install pywebview  → 있으면 창 앱으로, 없으면 기본 브라우저로 실행됩니다)
       (웹 배포 시엔 pip install gunicorn 도 필요 — requirements.txt에 포함됨)

exe 빌드(PyInstaller):
  pip install pyinstaller pywebview
  pyinstaller --onefile --noconsole --name "종목분석미니_v114" stock_analyzer_mini.py
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

import os, sys, math, re, sqlite3, threading, socket, webbrowser, time, subprocess
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
import requests
from flask import Flask, jsonify, request, render_template_string

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

APP_VERSION_HARDCODED = "v114"  # ⚠️ 이 프로그램의 진짜 버전. 새 버전을 낼 때마다 반드시 이 값을
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
HELP_CONTENT_ASOF = "v114"


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
        r = requests.get(f"https://m.stock.naver.com/api/stock/{ticker}/basic", headers=UA, timeout=6)
        if r.status_code != 200:
            return None
        return r.json()
    except Exception:
        return None


def _naver_mobile_integration(ticker):
    """💡 [v107] m.stock.naver.com/api/stock/{code}/integration — PER·PBR·EPS·BPS·배당·
       시총·52주·동일업종 PEER 종목까지 한 번에 제공. 실패 시 None."""
    try:
        r = requests.get(f"https://m.stock.naver.com/api/stock/{ticker}/integration", headers=UA, timeout=6)
        if r.status_code != 200:
            return None
        return r.json()
    except Exception:
        return None


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
        d = _naver_mobile_basic(ticker)
        if not d:
            return None, None
        name = d.get("stockName") or None
        market = None
        ext = (d.get("stockExchangeType") or {}).get("nameEng", "").upper()
        if ext in ("KOSPI", "KOSDAQ", "KONEX"):
            market = ext
        return name, market
    except Exception:
        return None, None


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
def get_price_data(ticker: str):
    if not FDR_OK:
        return None
    try:
        st = (datetime.now() - timedelta(days=420)).strftime("%Y-%m-%d")
        df = fdr.DataReader(ticker, st)
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

    basic = _naver_mobile_basic(ticker)
    if basic:
        details["risk_badges"] = _naver_trading_status_flags(basic)
        ext = (basic.get("stockExchangeType") or {}).get("nameEng", "").upper()
        if ext in ("KOSPI", "KOSDAQ", "KONEX"):
            details["market_type"] = ext

    integ = _naver_mobile_integration(ticker)
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

    try:
        url2 = f"https://comp.fnguide.com/SVO2/ASP/SVD_Main.asp?pGB=1&gicode=A{ticker}"
        r2 = requests.get(url2, headers=UA, timeout=6)
        soup2 = BeautifulSoup(r2.content.decode("utf-8", "replace"), "html.parser")
        ratio_th = soup2.find("th", string=lambda x: x and ("매출비중" in x or "매출비율" in x or "매출구성" in x))
        if ratio_th:
            tbody = ratio_th.find_parent("table").find("tbody")
            if tbody:
                revs = []
                for tr in tbody.find_all("tr"):
                    tds = tr.find_all(["th", "td"])
                    if len(tds) >= 2:
                        name = tds[0].text.strip()
                        ratio = tds[-1].text.strip()
                        if name and ratio and name not in ["계", "합계", "총계"] and ratio != "-":
                            revs.append(f"{name} ({ratio}%)")
                if revs:
                    details["revenue_breakdown"] = ", ".join(revs)
    except Exception as e:
        print(f"[기업개요] FnGuide 조회 오류(무시): {e}")

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
{risk_warning_section}

[이 리포트에 포함되지 않은 데이터 — 반드시 명시할 것]
- 외국인·기관 수급(순매수/순매도) 데이터 없음
- DART 다년도 재무제표(매출·영업이익 추이) 데이터 없음
- 최근 뉴스·공시 데이터 없음
- 위 항목들은 KRX 로그인 또는 DART API 키가 필요해 이 공개용 프로그램에는 포함되지 않았습니다.

[작성 지침 — 반드시 지킬 것]
1. 반드시 아래 순서대로, 각 섹션 제목은 [섹션명] 형식을 정확히 사용하세요.
2. 과장된 수식어 없이 객관적·냉철한 어조로 작성하세요. 확정되지 않은 것을 단정하지 마세요.
3. 항목별로 '•' 기호를 사용하고, 섹션 사이에 줄바꿈을 두세요.
4. <br> 같은 HTML 태그는 절대 사용하지 마세요. 마크다운(**굵게**, - 목록)만 사용하세요.
5. 매물대 데이터가 있는 경우, POC·VAH·VAL 수치를 원 단위로 정확히 인용하고 주식 초보자도 이해할 수 있도록 쉬운 말로 풀어 설명하세요.
6. 위에 명시한 "포함되지 않은 데이터"(수급·재무제표·뉴스/공시)에 대해서는 절대 있는 것처럼 지어내지 말고, [리스크 및 유의사항]에서 반드시 "이 리포트는 수급·재무제표 추이·최신 뉴스/공시를 포함하지 않으므로, 투자 결정 전 별도로 확인이 필요하다"고 명시하세요.
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

[3. 기술적 분석 심층]
- 이동평균 배열·RSI·거래량 배수·52주 위치·이격도를 종합해 현재 추세 국면(상승/하락/횡보, 과열/침체)을 판단하세요.
- 볼린저밴드 스퀴즈가 감지된 경우, 방향성 돌파 가능성과 그 방향을 가늠할 근거가 있는지 짚어주세요.

[4. 매물대 기술적 분석]
- POC(최대 매물 기준가)·VAL(핵심 지지선)·VAH(핵심 저항선)의 의미와 현재가가 그 사이 어디에 위치하는지 설명하세요.
- 초보 투자자도 이해할 수 있도록 어려운 용어는 괄호 안에 쉬운 말로 풀어 쓰세요.
- 매물대 데이터가 없다면 이 섹션은 "데이터 부족으로 매물대 분석 불가"로 간단히 처리하세요.

[5. 투자 전략 제안]
- 매물대 수치가 있다면 그 가격대를 근거로 구체적인 관심 진입 가격대와 참고 손절/익절 기준을 원 단위로 제안하세요. (예: "VAL({val_str}) 부근에서 분할 매수를 고려할 수 있으며...")
- 단기(1~2주)와 중기(1~3개월) 관점을 구분해서 서술하세요.
- 이것이 투자 추천이 아니라 데이터에 근거한 참고 의견임을 분명히 하세요.

[6. 리스크 및 유의사항]
- RSI 과열·이격도 과다 등 기술적으로 확인되는 리스크를 짚으세요.
- 반드시 위 6번 지침대로 "수급·재무제표 추이·뉴스/공시 데이터 미포함"을 명시하고, 투자 결정 전 확인을 권고하세요.
- 원금 손실 가능성과 투자 판단·책임이 투자자 본인에게 있음을 명시하세요.

[7. 해시태그]
#{name} #{ticker} #주식분석 #기술적분석 #매물대분석 #주린이
"""
    return prompt


# ══════════════════════════════════════════════════════════════
# Flask 라우트
# ══════════════════════════════════════════════════════════════
@app.route("/")
def index():
    return render_template_string(HTML_TEMPLATE, app_version=APP_VERSION)


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


@app.route("/api/analyze/<ticker>")
def api_analyze(ticker):
    if not FDR_OK:
        return jsonify({"error": "FinanceDataReader가 설치되어 있지 않습니다. "
                                  "pip install finance-datareader 후 다시 실행해 주세요."}), 400
    ticker = normalize_ticker(ticker)
    if not ticker:
        return jsonify({"error": "올바른 종목코드가 아닙니다."}), 400
    name, market = get_ticker_info(ticker)

    price_d = get_price_data(ticker)
    if not price_d:
        return jsonify({"error": f"주가 데이터를 가져오지 못했습니다. 종목코드를 확인해 주세요. ({ticker})"}), 400

    details, fundamentals = get_company_details_and_fundamentals(ticker)

    # 🐛 [v1.1] 검색 캐시에 없는 종목(목록 갱신이 실패했거나 아직 안 돌린 경우)도 코드 직접
    #   입력으로 분석은 되도록, 여기서 실제 종목명을 즉석에서 가져와 캐시에도 채워 넣는다
    #   (한 번 분석한 종목은 다음부터 검색에도 바로 뜨는 "자가 치유" 캐시).
    if not name:
        name, live_market = get_ticker_name_live(ticker)
        market = market or live_market
        if name:
            try:
                db_save_tickers([(ticker, name, market or "—")])
            except Exception:
                pass
        else:
            name = ticker

    return jsonify({
        "ticker": ticker, "name": name, "market": market or "—",
        "price": price_d,
        "details": details, "fundamentals": fundamentals,
        "delisting_risk": check_delisting_risk(price_d, details.get("risk_badges") or [], details.get("cap_eok")),
    })


@app.route("/api/ai-prompt/<ticker>")
def api_ai_prompt(ticker):
    if not FDR_OK:
        return jsonify({"error": "FinanceDataReader가 설치되어 있지 않습니다."}), 400
    ticker = normalize_ticker(ticker)
    name, market = get_ticker_info(ticker)
    if not name:
        name, live_market = get_ticker_name_live(ticker)
        market = market or live_market
        name = name or ticker
    price_d = get_price_data(ticker)
    if not price_d:
        return jsonify({"error": "주가 데이터를 가져오지 못했습니다."}), 400
    details, fundamentals = get_company_details_and_fundamentals(ticker)
    risk = check_delisting_risk(price_d, details.get("risk_badges") or [], details.get("cap_eok"))
    prompt = build_ai_prompt(ticker, name, market or "—", price_d, fundamentals, details,
                              delisting_risk=risk)
    return jsonify({"prompt": prompt})


HTML_TEMPLATE = r"""
<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1,user-scalable=no">
<title>종목분석 미니 {{ app_version }}</title>
<script>window.__APP_VER__ = "{{ app_version }}";</script>
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
  .brand{color:#fff; font-weight:800; font-size:16px; white-space:nowrap; letter-spacing:-.2px;}
  .brand span{color:var(--gold);}
  .verTag{color:rgba(255,255,255,.4)!important; font-size:10px!important; font-weight:600!important; letter-spacing:0;}
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
  <div class="brand">📈 종목분석<span> 미니</span> <span class="verTag">{{ app_version }}</span></div>
  <div class="searchWrap">
    <input id="searchInput" class="searchInput" type="text" placeholder="종목명 또는 코드를 입력하세요 (예: 삼성전자, 005930)" autocomplete="off">
    <div id="searchDrop" class="searchDrop"></div>
  </div>
  <button class="refreshBtn" onclick="refreshTickers()">🔄 종목목록 갱신</button>
  <a class="refreshBtn" href="/help" target="_blank" rel="noopener" style="text-decoration:none;">❓ 도움말</a>
  <a class="blogBtn" href="https://blog.naver.com/okykr" target="_blank" rel="noopener"
     title="이 프로그램을 만든 제작자의 투자 블로그입니다">✍️ 제작자 블로그 ↗</a>
</div>

<div class="wrap">
  <div id="emptyState" class="empty">
    <div class="big">🔍</div>
    종목명이나 종목코드를 검색해서<br>기술적분석 리포트를 확인해 보세요.
    <div style="margin-top:18px;font-size:12px;">FinanceDataReader · 네이버 공개 데이터 기반 · 로그인 불필요</div>
    <div style="margin-top:6px;font-size:11.5px;">검색이 안 되면 6자리 종목코드(예: 005930)를 입력하고 Enter를 눌러도 바로 분석돼요.</div>

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

    <div class="card heroCard">
      <div class="heroLeft">
        <div class="heroName" id="heroName">—</div>
        <div class="heroTicker" id="heroTicker">—</div>
        <div class="heroPrice" id="heroPrice">—</div>
        <div class="heroChange" id="heroChange">—</div>
      </div>
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

    <div class="card" id="overviewCard" style="display:none;">
      <h3>🏢 기업개요 <span id="overviewSourceBadge" class="cardBadge" style="background:#f1f5f9;color:#64748b;border-color:#e2e8f0;"></span></h3>
      <div class="overviewText" id="overviewText"></div>
      <div class="revBreak" id="revBreak"></div>
    </div>

    <div class="card" id="peerCard" style="display:none;">
      <h3>🤝 동일업종 비교 <span class="cardBadge">네이버 증권엔 없는 정보</span></h3>
      <div id="consensusBox" class="consensusBox" style="display:none;"></div>
      <div class="peerGrid" id="peerGrid"></div>
      <div class="peerNote">※ 가격·등락률만 제공됩니다(PER/PBR은 이 데이터 소스에서 확인되지 않아 표시하지 않습니다).</div>
    </div>

    <div class="card">
      <h3>🤖 AI 분석 (수동 모드)</h3>
      <div class="aiHint">이 앱은 AI를 직접 호출하지 않습니다. 아래 버튼을 누르면 분석 프롬프트가
        자동으로 복사되고 해당 AI 사이트의 새 탭이 열립니다 — 그 화면에 <b>Ctrl+V(붙여넣기)</b>만 하시면 됩니다.
        받은 답변을 복사해서 아래 칸에 붙여넣으면 <b>자동으로</b> 보기 좋게 정리해서 보여드립니다.</div>
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
      <textarea id="aiPasteBox" class="pasteBox" placeholder="여기에 AI의 답변을 붙여넣으세요 — 붙여넣는 즉시 자동으로 정리돼서 표시됩니다."></textarea>
      <div class="aiBtnRow" style="margin-top:10px;">
        <button class="btn btn-ghost" onclick="renderAiResult()">🔄 다시 표시</button>
      </div>
      <div class="aiResult" id="aiResult"></div>
    </div>

    <div class="footNote">
      본 리포트는 공개된 시세·재무 데이터를 기술적으로 계산한 참고 자료이며 투자 추천이 아닙니다.<br>
      투자 판단과 그 책임은 전적으로 투자자 본인에게 있습니다. · Data: FinanceDataReader, 네이버금융<br>
      <button class="termsLink" onclick="showDisclaimer(true)">이용 안내 및 면책 조항 다시 보기</button>
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
function analyze(ticker){
  showToast('⏳ 분석 중입니다...');
  fetch('/api/analyze/' + ticker).then(r=>r.json()).then(data=>{
    if(data.error){ showToast('⚠ ' + data.error); return; }
    CUR = data;
    // 🐛 [v108] "종합점수가 표시되도록 수정" — 원인은 renderResult() 안에서 차트 등
    // 일부만 실패해도(예: ApexCharts CDN 로드 지연/실패) 예외가 전체를 중단시켜,
    // 이미 화면에 반영된 점수까지 포함해 결과 영역 자체가 display:none으로 안 열리는
    // 것이었다. result를 먼저 연 뒤 렌더링하고, renderResult 내부도 각 구간을
    // 개별적으로 보호해 한 구간의 실패가 다른 구간(특히 점수)까지 끌고 내려가지
    // 않도록 했다.
    document.getElementById('emptyState').style.display = 'none';
    document.getElementById('result').style.display = 'block';
    try{
      renderResult(data);
    }catch(e){
      console.error('[renderResult]', e);
      showToast('⚠ 일부 항목 표시 중 오류가 있었지만 나머지는 정상 표시됩니다.');
    }
    document.getElementById('aiPromptBox').value = '';
    document.getElementById('aiPromptBox').style.display = 'none';
    document.getElementById('aiPasteBox').value = '';
    document.getElementById('aiResult').classList.remove('show');
  }).catch(()=>showToast('⚠ 분석 중 오류가 발생했습니다.'));
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

function _copyText(text){
  let copied = false;
  try{
    if(navigator.clipboard && navigator.clipboard.writeText){
      navigator.clipboard.writeText(text);
      copied = true;
    }
  }catch(e){}
  if(!copied){
    try{
      const ta = document.createElement('textarea');
      ta.value = text; ta.style.position = 'fixed'; ta.style.left = '-9999px';
      document.body.appendChild(ta); ta.focus(); ta.select();
      document.execCommand('copy');
      document.body.removeChild(ta);
      copied = true;
    }catch(e){}
  }
  return copied;
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

// 🚀 [v1.2] "기존 프로그램처럼 AI에 연결" — 버튼 하나로 프롬프트 복사 + 해당 AI 사이트 새 탭
//   열기까지 한 번에 처리한다. 그 화면에 사용자가 Ctrl+V만 하면 바로 분석이 진행된다.
function copyAndOpenAI(which){
  if(!CUR){ showToast('먼저 종목을 분석해 주세요.'); return; }
  const svcName = AI_SERVICE_NAMES[which] || which;
  fetch('/api/ai-prompt/' + CUR.ticker).then(r=>r.json()).then(d=>{
    if(d.error){ showToast('⚠ ' + d.error); return; }
    const box = document.getElementById('aiPromptBox');
    box.value = d.prompt;
    const copied = _copyText(d.prompt);
    _openExternal(AI_SERVICE_URLS[which]);
    showToast(copied
      ? '📋 프롬프트 복사 완료 — ' + svcName + ' 화면에 Ctrl+V로 붙여넣어 주세요.'
      : '⚠ 자동 복사에 실패했습니다. 프롬프트 보기를 눌러 직접 복사해 주세요.');
  }).catch(()=>showToast('⚠ 프롬프트 생성 중 오류가 발생했습니다.'));
}

function copyAiPrompt(){
  if(!CUR){ showToast('먼저 종목을 분석해 주세요.'); return; }
  fetch('/api/ai-prompt/' + CUR.ticker).then(r=>r.json()).then(d=>{
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
      fetch('/api/ai-prompt/' + CUR.ticker).then(r=>r.json()).then(d=>{
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
        2. "AI 분석(수동 모드)" 카드에서 원하는 AI(제미나이·챗GPT·클로드) 버튼을 누르면 프롬프트가 자동 복사되고 해당 AI 사이트 새 탭이 열립니다.<br>
        3. 열린 사이트에서 Ctrl+V(붙여넣기) 후 전송합니다.<br>
        4. AI가 준 답변 전체를 복사해서, 이 프로그램의 답변 입력 칸에 붙여넣으면 자동으로 보기 좋게 정리되어 화면에 표시됩니다.</span>
      </dd>
      <dt>주의할 점</dt>
      <dd>이 AI 리포트는 외국인·기관 수급, 다년도 재무제표 추이, 최신 뉴스·공시를 포함하지 않습니다(공개판 한계). 투자 결정 전 반드시
        별도로 확인하시고, 리포트 내용은 투자 추천이 아닌 참고 의견입니다.</dd>
    </dl>
    <a class="back-to-top" href="#top">↑ 목차로</a>
  </section>

  <div class="footNote">이 도움말의 모든 설명은 일반적인 증권 용어 해설이며, 특정 종목에 대한 투자 조언이 아닙니다.</div>

</div>
</body>
</html>
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

init_db()
threading.Thread(target=build_ticker_cache, daemon=True).start()


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
