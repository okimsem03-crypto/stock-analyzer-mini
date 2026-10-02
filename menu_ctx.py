"""메뉴 모듈 연결부 — 메뉴 하나가 파일 하나(menu_<이름>.py).

새 메뉴를 만드는 방법(요약)
  1. menu_<이름>.py 를 만들고 register() 함수를 둔다.(폴더 없이 본체 파일과 같은 곳에 둔다)
  2. register() 안에서 C.register_menu(...) 로 메뉴를 등록하고, 화면·API는 Blueprint(bp)에 붙여 돌려준다.
  3. 아래 MODULES 목록에 이름을 한 줄 추가한다.
메뉴가 누구에게 보이는지(공개·회원·관리자 전용)는 메뉴 목록의 "접근 등급" 한 칸으로만 정해지고,
관리자 화면의 [메뉴·설정]에서 바꾼다. 메뉴 파일 안에서 따로 판단하지 않는다.

모듈은 본체(stock_analyzer_mini.py)의 함수를 C 로 호출한다(C._dbx(...) 처럼). C 는 '지금 실행 중인 본체'를
그대로 가리키므로 시험에서 본체 함수를 바꿔 끼워도 모듈에 반영된다.
"""

MODULES = ["delist", "dataimport"]

_core = None


class _Ctx:
    def __getattr__(self, name):
        if _core is None:
            raise AttributeError(name)
        return getattr(_core, name)


C = _Ctx()


def bind(core_module):
    global _core
    _core = core_module
