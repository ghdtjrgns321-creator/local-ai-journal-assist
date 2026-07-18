"""다사(多社) DataSynth 출력에서 한 회사의 원장만 잘라 단일법인 base를 만든다.

행 선택만 하는 투영(projection)이다 — 값 재작성 0. v42 덧칠(normalize/append 계열)이
값을 고치다 계정-적요 결합을 깨뜨린 전례가 있어, 이 스크립트는 의도적으로
"행을 고르는 것" 이상을 하지 않는다.

사용:
    uv run python tools/scripts/filter_single_company.py \
        --input <생성 출력 dir> --output <단일법인 base dir> --company C001

- journal_entries.csv 와 journal_entries_YYYY.csv 를 company_code 로 필터.
- 그 외 파일·디렉토리(사이드카)는 그대로 복사한다. 사이드카의 타사 레코드 정리는
  룰 오염이 실측되면 그때 추가한다(선제 가공 금지).
"""

from __future__ import annotations

import argparse
import re
import shutil
from pathlib import Path

import pandas as pd

JOURNAL_PATTERN = re.compile(r"^journal_entries(_\d{4})?\.csv$")


def filter_journals(src: Path, dst: Path, company: str) -> dict[str, tuple[int, int]]:
    """journal CSV들을 필터해 dst에 쓴다. 반환: 파일별 (남긴 행, 원본 행)."""
    result: dict[str, tuple[int, int]] = {}
    for f in sorted(src.iterdir()):
        if not (f.is_file() and JOURNAL_PATTERN.match(f.name)):
            continue
        df = pd.read_csv(f, dtype=str, low_memory=False)
        kept = df[df["company_code"].astype(str) == company]
        kept.to_csv(dst / f.name, index=False)
        result[f.name] = (len(kept), len(df))
    return result


def copy_rest(src: Path, dst: Path) -> int:
    """journal CSV 외 전부를 그대로 복사한다. 반환: 복사한 최상위 항목 수."""
    copied = 0
    for item in sorted(src.iterdir()):
        if item.is_file() and JOURNAL_PATTERN.match(item.name):
            continue  # 위에서 필터본으로 대체됨
        target = dst / item.name
        if item.is_dir():
            shutil.copytree(item, target, dirs_exist_ok=True)
        else:
            shutil.copy2(item, target)
        copied += 1
    return copied


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--company", required=True)
    args = parser.parse_args()

    args.output.mkdir(parents=True, exist_ok=True)
    journals = filter_journals(args.input, args.output, args.company)
    if "journal_entries.csv" not in journals:
        raise SystemExit(f"journal_entries.csv 가 {args.input} 에 없다")
    copied = copy_rest(args.input, args.output)

    for name, (kept, total) in journals.items():
        print(f"{name}: {kept:,} / {total:,} 행 유지 ({args.company})")
    print(f"사이드카 등 복사: {copied}개 항목")


if __name__ == "__main__":
    main()
