"""룰 코드 → 한국어 라벨 매핑 (단일 출처).

Why: tab_phase1 / tab_comparison / 차트 컴포넌트가 모두 같은 한국어 룰 이름을
     필요로 한다. 한 곳에 모아 import 해서 사용한다. 새 룰 추가 시 여기만 수정.

Why(2026-08-04 어휘 통일): 종전에는 이 사전·`phase1_case_builder` 의 테마별 사전·
     `config/combo_builder.yaml` 의 label 이 같은 룰을 서로 다른 이름으로 불렀다
     (전수 대조 29/29 불일치 — 예: L2-03 이 화면마다 "중복 분개"/"근접일자 중복 전표"/
     "중복 전표"). 감사인이 한 룰을 세 이름으로 보게 되므로 **README·조합 빌더 어휘를
     기준으로 통일**한다. 어휘 22종은 `combo_builder.yaml` 의 label 과 글자까지 같아야
     하며 `tests/modules/test_dashboard/test_rule_labels.py` 가 이를 강제한다.
     빌더 어휘 밖(L4-02·D01·D02)은 대조 대상이 아니다.
"""

from __future__ import annotations

RULE_NAMES_KR: dict[str, str] = {
    # 데이터 정합성 4 — README §3-2 갈래별 룰 구성
    "L1-01": "차대균형",
    "L1-02": "필수필드",
    "L1-03": "무효계정",
    "L1-08": "기간불일치",
    # 수법(특징) 13 — combo_builder.yaml features
    "L1-04": "승인한도초과",
    "L1-05": "자기승인",
    "L1-06": "직무분리 겸직",
    "L1-07": "승인생략",
    "L1-07-02": "유령승인자",
    "L2-01": "한도 직하 분할",
    "L2-02": "중복지급",
    "L2-03": "중복 전표",
    "L3-02": "수기",
    "L3-05": "휴일 입력",
    "L3-06": "심야 입력",
    "L3-07": "소급기표",
    "L4-04": "희소계정쌍",
    # 대상(몸통) 9 — combo_builder.yaml bodies
    "L2-04": "비용자산화",
    "L2-05": "역분개",
    "L3-03": "관계사",
    "L3-04": "기말결산",
    "L3-09": "가수금 체류",
    "L3-10": "추정계정",
    "L3-11": "컷오프",
    "L4-01": "매출과대",
    "L4-03": "이상고액",
    # 모집단 신호 3 — PHASE1-2 배지
    "L3-12": "업무범위 집중",
    "L4-05": "심야 배치",
    "L4-06": "배치 이상",
    # 빌더 어휘 밖(PHASE1-2 자기 큐)
    "L4-02": "벤포드 위반",
    "D01": "계정 활동 변동",
    "D02": "비율 분포 변동",
}


def rule_label(rule_id: str, *, with_code: bool = True) -> str:
    """룰 코드를 한국어 라벨로 변환. 미정의 룰은 코드 그대로 반환."""
    name = RULE_NAMES_KR.get(rule_id)
    if name is None:
        return rule_id
    return f"{rule_id} · {name}" if with_code else name
