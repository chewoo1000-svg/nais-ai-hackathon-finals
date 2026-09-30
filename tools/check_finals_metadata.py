"""담당 번호와 본선 작업 시각의 의미를 읽기 전용으로 검사한다."""

import json
import re
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXPECTED = {"이영": 0, "이채우": 1, "임도윤": 2, "조지현": 3}


def check():
    # 수정 이유: 담당자 고정 번호를 릴리스 증가 번호와 혼동하는 문제를 잡는다.
    failures = []
    team = json.loads((ROOT / "TEAM_VERSIONS.json").read_text(encoding="utf-8"))
    actual = {entry["name"]: entry["version"] for entry in team["contributors"]}
    if actual != EXPECTED:
        failures.append("담당자 번호 불일치")
    # [수정: 0 이영] 2026-09-30T21:15:33+09:00 — VERSION 파일은 팀원 4명이 함께 쓰므로 3 고정이면
    # 다른 담당자가 올릴 때마다 FAIL. 마지막으로 올린 담당 번호(0~3, "0.1.0"처럼 앞자리)인지 검사한다.
    chat = team["this_chat"]
    if EXPECTED.get(chat["name"]) != chat["version"] or chat["commit_prefix"] != f"[{chat['version']} {chat['name']}]":
        failures.append("이 채팅 담당 번호 불일치")
    version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    lead = version.split(".")[0]
    if lead not in {str(v) for v in EXPECTED.values()}:
        failures.append("VERSION 앞자리가 담당 번호가 아님")

    # 수정 이유: 문서 갱신과 실행 시각을 구분하며 KST 작업 메타데이터만 검사한다.
    # 논문 발행일, 관측일, 스키마 규격 연도, Git 시각을 수정 대상으로 삼지 않는다.
    baseline = datetime.fromisoformat(team["finals_started_at_kst"])
    now = datetime.now(baseline.tzinfo)
    json_count = 0
    for path in [ROOT / "TEAM_VERSIONS.json", *sorted((ROOT / "docs").rglob("*.json"))]:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            json_count += 1
            if not isinstance(data, dict):
                continue
            for key in ("recorded_at_kst", "document_updated_at_kst", "review_started_at_kst"):
                value = data.get(key)
                if value is None:
                    continue
                stamp = datetime.fromisoformat(value)
                if stamp.utcoffset() != baseline.utcoffset() or not baseline <= stamp <= now:
                    failures.append(f"{path.relative_to(ROOT)}: {key} 불일치")
        except (ValueError, KeyError, TypeError) as exc:
            failures.append(f"{path.relative_to(ROOT)}: 형식 오류 {type(exc).__name__}")

    # 수정 이유: 문서명 변경 뒤 깨진 내부 링크가 남는 문제를 확인한다.
    for name in ("README.md", "AGENTS.md"):
        for target in re.findall(r"\]\(([^)]+)\)", (ROOT / name).read_text(encoding="utf-8")):
            if "://" not in target and not (ROOT / target.split("#", 1)[0]).exists():
                failures.append(f"{name}: 연결 파일 누락 {target}")

    return {
        "contributor_version": int(lead) if lead.isdigit() else None,
        "checked_at_kst": now.isoformat(timespec="seconds"),
        "scope": "담당 번호·JSON 형식·선택된 KST 작업 필드·핵심 문서 링크",
        "json_files_checked": json_count,
        "status": "PASS" if not failures else "FAIL",
        "failures": failures,
        "limits": "앱 동작·날짜의 사실성·논문·LLM 성능을 검증한 결과가 아님",
    }


if __name__ == "__main__":
    result = check()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    sys.exit(0 if result["status"] == "PASS" else 1)
