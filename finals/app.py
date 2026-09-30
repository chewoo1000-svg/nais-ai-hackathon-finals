"""[0 이영] 2026-09-30 KST: 원문·검산·직접 승인·재열기를 하나의 본선 동선으로 연결한다."""
from __future__ import annotations

import html
import json
from pathlib import Path
import re
import sys

import pandas as pd
import streamlit as st

AGENT_ROOT = Path(__file__).resolve().parent
# 수정 이유: Desktop 통합 저장소의 core/data와 본선 전용 모듈을 함께 사용한다.
for module_root in (AGENT_ROOT.parent, AGENT_ROOT):
    if str(module_root) not in sys.path:
        sys.path.insert(0, str(module_root))

from finals_provider import ProviderError, availability, complete_json

st.set_page_config(page_title="근거관문 · 버전 0", page_icon="◈", layout="wide", initial_sidebar_state="expanded")

# 수정 이유: 시각 대비·16px 본문·키보드 포커스·좁은 화면의 재배치로 검토 동선을 읽기 쉽게 한다.
st.markdown("""
<style>
:root{--ink:#152033;--navy:#172e50;--muted:#536277;--line:#d9e1eb;--paper:#fff;--bg:#f5f7fa}
.stApp{font-family:'Malgun Gothic','Segoe UI',sans-serif;color:var(--ink);background:var(--bg)}
.stMainBlockContainer{max-width:1440px;padding-top:2.4rem;padding-bottom:4rem}
p,label,[data-testid='stMarkdownContainer']{font-size:16px;line-height:1.65}
h1{font-size:48px!important;letter-spacing:-.045em;color:var(--navy);line-height:1.12!important}
h2{font-size:25px!important;letter-spacing:-.03em}h3{font-size:19px!important}
[data-testid='stSidebar']{border-right:1px solid var(--line)}
[data-testid='stVerticalBlockBorderWrapper']>div{background:var(--paper);border-color:var(--line)!important;border-radius:12px!important}
.stButton button,.stDownloadButton button{min-height:46px;font-weight:600;border-radius:8px;transition:background .16s ease}
button:focus-visible,input:focus-visible,textarea:focus-visible{outline:3px solid #3469a8!important;outline-offset:3px!important}
[data-testid='stCaptionContainer']{color:var(--muted);font-size:14px!important}
.final-kicker{font-size:12px;letter-spacing:.16em;font-weight:700;color:var(--muted);margin-bottom:12px}
.final-summary{color:var(--muted);max-width:760px;font-size:17px;line-height:1.7;margin-bottom:24px}
.final-rule{height:3px;background:var(--navy);margin:18px 0 28px;width:72px}
.final-step{font-size:12px;letter-spacing:.1em;color:var(--muted);font-weight:700;margin:4px 0 8px}
.final-note{border-left:3px solid var(--navy);padding:12px 16px;background:#edf2f8;line-height:1.7;overflow-wrap:anywhere}
kbd{background:#e8edf4;border:1px solid #bdcadb;border-radius:4px;padding:2px 6px;font-size:12px}
@media(max-width:760px){h1{font-size:36px!important}.stMainBlockContainer{padding-top:1.5rem;padding-left:1rem;padding-right:1rem}}
@media(prefers-reduced-motion:reduce){*{animation:none!important;transition:none!important}}
</style>
""", unsafe_allow_html=True)

CATEGORIES = {"normal":"정상", "mismatch":"수치 불일치", "evidence_missing":"근거 부족", "data_changed":"자료 변경"}
STATE_NAMES = {"ARITHMETIC_MATCH":"수치 일치", "MATCH":"수치 일치", "ARITHMETIC_MISMATCH":"수치 불일치", "MISMATCH":"수치 불일치", "BLOCK":"보류", "BLOCKED":"보류", "INPUT_CHANGED":"변경 후 재사용 차단", "APPROVED":"사람 확인 완료", "PROPOSED":"후보 접수", "NOT_RUN":"미실행", "SUPPORTED_PREVIEW":"조건 검산 완료", "CONFLICT_PREVIEW":"수치 불일치", "MISSING":"근거 부족", "BLOCKED_CHANGED_INPUT":"변경 후 재사용 차단"}
MODES = {"수동 작성":"manual", "실시간 AI":"live", "저장 응답 재생":"replay"}
SENSITIVE = {"api_key", "apikey", "authorization", "password", "secret", "access_token", "refresh_token", "credential", "credentials"}


def public_snapshot(value):
    """수정 이유: 원출력·보고서를 표시하거나 내려받을 때 인증 값이 함께 남는 경로를 막는다."""
    if isinstance(value, dict):
        return {str(key):public_snapshot(item) for key,item in value.items() if str(key).lower() not in SENSITIVE}
    if isinstance(value, (list,tuple)):
        return [public_snapshot(item) for item in value]
    if isinstance(value, str):
        return re.sub(r"sk-[A-Za-z0-9_\-]{12,}", "[인증 값 제외]", value)
    if value is None or isinstance(value, (bool,int,float)):
        return value
    return str(value)


def state_of(report):
    return str(report.get("state", report.get("status", report.get("action", "NOT_RUN"))))


def approved(report):
    approval = report.get("human_approval") if report else None
    return approval is True or isinstance(approval, dict) and approval.get("status") == "APPROVED"


def invalidate_review():
    # 수정 이유: 후보·작성 경로가 바뀐 뒤 검산이나 사람 승인을 재사용하지 않는다.
    st.session_state.pop("fin_report", None)
    st.session_state.pop("fin_exported_report", None)
    st.session_state["fin_human_confirm"] = False
    st.session_state["fin_reason"] = ""


def notice_error(error):
    code = str(error) if isinstance(error, ProviderError) else str(getattr(error, "code", "INPUT_OR_CONNECTION_ERROR"))
    if code in {"credit_balance_exhausted", "insufficient_quota", "RATE_LIMITED", "INSUFFICIENT_QUOTA", "MODEL_HTTP_429"}:
        st.error("AI 생성 요청이 사용 한도 문제로 중단됐습니다. 수동 작성으로 계속할 수 있습니다.")
    elif str(error) == "REPORT_INTEGRITY_MISMATCH":
        st.error("보고서 검증 지문이 맞지 않습니다. 화면에서 내려받은 파일을 그대로 다시 열어 주세요.")
    else:
        st.error("입력 또는 연결을 확인하지 못했습니다. 조건과 공개 원문을 다시 확인하세요.")
    st.session_state["fin_action_error"] = code


def reset_case(case_id):
    # 수정 이유: 사례·입력이 바뀌면 후보, 검산, 직접 확인과 승인 사유를 함께 초기화한다.
    for key in ("fin_report", "fin_candidate_text", "fin_human_confirm", "fin_reason", "fin_action_error", "fin_reopened", "fin_exported_report"):
        st.session_state.pop(key, None)
    st.session_state["fin_case_id"] = case_id


def health_record():
    try:
        data = json.loads((AGENT_ROOT.parent / "docs/0_이영_AI연결점검.json").read_text(encoding="utf-8"))
        return {"status":data.get("status"),"checked_at_kst":data.get("checked_at_kst"),"code":data.get("generation_check",{}).get("error_code")}
    except (OSError,ValueError,TypeError):
        return {}


st.markdown('<div class="final-kicker">RESEARCH VERIFICATION / FINALS 2026</div>', unsafe_allow_html=True)
st.title("근거관문")
st.caption("본선 연구 검산 · 버전 0")
st.markdown('<div class="final-summary">원문에서 조건을 확인하고, 데이터로 다시 계산합니다.<br>근거와 결과를 검토한 뒤 사람이 직접 승인합니다.</div><div class="final-rule"></div>', unsafe_allow_html=True)

try:
    import finals_cases as cases
    import finals_pipeline as pipeline
except ImportError:
    st.error("본선 분석 모듈을 준비 중입니다. 연결이 완료되면 사례 검토를 시작할 수 있습니다.")
    st.stop()

catalog = cases.list_cases()
with st.sidebar:
    st.caption("본선 작업 · 버전 0 · 이영")
    st.subheader("검토할 사례")
    category = st.selectbox("사례 유형", ["전체",*CATEGORIES.values()], key="fin_category")
    selected = [item for item in catalog if category == "전체" or CATEGORIES.get(item.get("category")) == category]
    if not selected:
        st.info("이 유형에 등록된 사례가 없습니다.")
        st.stop()
    case_id = st.selectbox("등록 사례", [item["id"] for item in selected], format_func=lambda cid:next(item["label"] for item in selected if item["id"] == cid), key="fin_case_select")
    if st.session_state.get("fin_case_id") != case_id:
        reset_case(case_id)
    mode_label = st.radio("후보 작성 방법", list(MODES), key="fin_mode",on_change=invalidate_review)
    st.divider()
    status = availability()
    st.markdown("**AI 연결**")
    if status.get("available"):
        st.caption("인증 설정 있음 · " + str(status.get("model", "모델 확인 필요")))
        previous = health_record()
        if previous.get("status") == "GENERATION_BLOCKED":
            st.warning("가장 최근 생성 요청은 사용 한도 문제로 중단됐습니다.")
            st.caption("실제 응답이 생성되기 전에는 AI 분석을 완료로 표시하지 않습니다.")
    else:
        st.info("AI 연결 설정이 없습니다. 수동 작성으로 검토할 수 있습니다.")
    st.markdown("<kbd>Tab</kbd> 이동 · <kbd>Enter</kbd> 실행", unsafe_allow_html=True)

context = cases.load_case(case_id)
report = st.session_state.get("fin_report")
summary = st.columns([1.3,1,1])
summary[0].caption("선택 사례")
summary[0].write(next(item["label"] for item in catalog if item["id"] == case_id))
summary[1].caption("검산 상태")
summary[1].write(STATE_NAMES.get(state_of(report), state_of(report)) if report else "미실행")
summary[2].caption("사람 확인")
summary[2].write("직접 승인 완료" if approved(report) else "미승인")
st.divider()

left, right = st.columns([1.08,1], gap="large")
with left:
    with st.container(border=True):
        st.markdown('<div class="final-step">01 / SOURCE</div>', unsafe_allow_html=True)
        st.subheader("원문과 자료")
        st.caption(str(context.get("source_location", "원문 위치 확인 필요")))
        quote = str(context.get("source_quote", ""))
        st.markdown('<div class="final-note">' + html.escape(quote or "확인 가능한 인용이 없습니다.") + '</div>', unsafe_allow_html=True)
        if context.get("paper_url"):
            st.link_button("공개 원문 열기", context["paper_url"])
        st.caption("등록된 자료 미리보기 · 상위 8행")
        frame = context.get("dataframe")
        if frame is not None:
            if not isinstance(frame,pd.DataFrame):
                frame = pd.DataFrame(frame)
            st.dataframe(frame.head(8), use_container_width=True, hide_index=True)
            st.caption(f"등록 자료 {len(frame):,}행 · {len(frame.columns)}열")
        else:
            st.info("원자료 미리보기가 제공되지 않았습니다.")

    with st.container(border=True):
        st.markdown('<div class="final-step">02 / CONDITIONS</div>', unsafe_allow_html=True)
        st.subheader("분석 조건 검토")
        st.caption("원문이 말하는 대상·분모·단위와 실제 계산 조건을 대조합니다.")
        candidate = {}
        try:
            candidate = json.loads(st.session_state.get("fin_candidate_text", "{}"))
        except (ValueError,TypeError):
            pass
        fields = [("분석 방법","method"),("사용 열","column"),("포함·제외 조건","filters"),("분모","denominator"),("결측 처리","missing_policy"),("단위","unit")]
        rows = [{"검토 항목":label,"후보 조건":json.dumps(candidate.get(key),ensure_ascii=False) if candidate.get(key) is not None else "미확인","원문 확인":"직접 대조 필요"} for label,key in fields]
        st.dataframe(pd.DataFrame(rows),use_container_width=True,hide_index=True)
        if report and report.get("validation"):
            with st.expander("조건 검사 상세"):
                st.json(public_snapshot(report["validation"]))

with right:
    with st.container(border=True):
        st.markdown('<div class="final-step">03 / CANDIDATE</div>', unsafe_allow_html=True)
        st.subheader("계산 후보")
        mode = MODES[mode_label]
        if mode == "manual":
            st.caption("등록된 조건을 불러온 뒤 JSON 후보를 수정할 수 있습니다. 불러오기만으로 실행하거나 승인하지 않습니다.")
            if st.button("수동 후보 불러오기", key="fin_manual_load", use_container_width=True):
                invalidate_review()
                st.session_state["fin_candidate_text"] = json.dumps(context["manual_proposal"],ensure_ascii=False,indent=2)
                st.rerun()
        elif mode == "live":
            st.caption("선택한 공개 원문과 허용된 자료 정보로 실제 후보 생성을 요청합니다.")
            if st.button("실시간 AI 연결 다시 확인", key="fin_live_generate", disabled=not status.get("available",False), use_container_width=True):
                try:
                    invalidate_review()
                    with st.spinner("공개 원문에서 조건 후보를 요청하고 있습니다…"):
                        fresh = pipeline.run_case(case_id,mode="live",provider=complete_json)
                    st.session_state["fin_report"] = public_snapshot(fresh)
                    proposed = fresh.get("candidate",fresh.get("proposal"))
                    if proposed is not None:
                        st.session_state["fin_candidate_text"] = json.dumps(proposed,ensure_ascii=False,indent=2)
                    st.rerun()
                except Exception as exc:
                    notice_error(exc)
        else:
            replays = pipeline.list_replays() if hasattr(pipeline,"list_replays") else []
            replays = [item for item in replays if Path(item["path"]).is_file()]
            if not replays:
                st.info("저장된 실제 AI 응답이 없습니다. 수동 작성 또는 실시간 AI를 선택하세요.")
            replay_path = st.selectbox("실제 응답 파일",[item["path"] for item in replays],format_func=lambda path:Path(path).name,key="fin_replay_file",disabled=not replays) if replays else None
            if st.button("저장 응답으로 검토",key="fin_replay_run",disabled=not replays,use_container_width=True):
                try:
                    st.session_state["fin_report"] = public_snapshot(pipeline.run_case(case_id,mode="replay",replay_path=replay_path))
                    st.rerun()
                except Exception as exc:
                    notice_error(exc)
        candidate_text = st.text_area("후보 JSON", key="fin_candidate_text",height=240,on_change=invalidate_review,help="원문 보고값과 자료 지문을 유지하고, 알 수 없는 조건은 추측하지 않습니다.")
        if st.button("조건 검산",key="fin_compute",type="primary",disabled=not candidate_text.strip(),use_container_width=True):
            try:
                with st.spinner("조건과 원문을 대조하고 다시 계산하고 있습니다…"):
                    st.session_state["fin_report"] = public_snapshot(pipeline.run_case(case_id,mode="manual",proposal_text=candidate_text))
                st.session_state["fin_human_confirm"] = False
                st.session_state["fin_reason"] = ""
                st.rerun()
            except Exception as exc:
                notice_error(exc)

    report = st.session_state.get("fin_report")
    if report:
        with st.container(border=True):
            st.markdown('<div class="final-step">04 / RESULT</div>', unsafe_allow_html=True)
            st.subheader("검산 결과")
            state = state_of(report)
            if state in {"ARITHMETIC_MATCH","MATCH","APPROVED","SUPPORTED_PREVIEW"}:
                st.success(STATE_NAMES.get(state,state))
            elif "MISMATCH" in state or state in {"BLOCK","BLOCKED","INPUT_CHANGED","MISSING","BLOCKED_CHANGED_INPUT"}:
                st.warning(STATE_NAMES.get(state,state))
            else:
                st.info(STATE_NAMES.get(state,state))
            if report.get("calculation"):
                st.json(public_snapshot(report["calculation"]))
            if report.get("reason"):
                st.write(str(report["reason"]))
            critique = report.get("critique")
            if critique:
                with st.expander("검토 의견",expanded=True):
                    st.json(public_snapshot(critique)) if isinstance(critique,(dict,list)) else st.write(str(critique))
            if st.button("자료 변경 후 재검산",key="fin_change",use_container_width=True):
                try:
                    st.session_state["fin_report"] = public_snapshot(pipeline.recheck_changed_input(report))
                    st.session_state["fin_human_confirm"] = False
                    st.session_state["fin_reason"] = ""
                    st.rerun()
                except Exception as exc:
                    notice_error(exc)

        with st.container(border=True):
            st.markdown('<div class="final-step">05 / HUMAN REVIEW</div>', unsafe_allow_html=True)
            st.subheader("사람의 최종 확인")
            st.caption("수치 일치는 연구 내용의 타당성을 증명하지 않습니다. 원문과 여섯 조건을 직접 확인한 사람이 사유를 남깁니다.")
            confirmed = st.checkbox("원문 근거와 분석 조건을 직접 확인했습니다",key="fin_human_confirm")
            reason = st.text_area("승인 사유",key="fin_reason",height=100,placeholder="어떤 근거와 조건을 확인했는지 적어 주세요.")
            can_approve = report.get("can_approve") is True and not approved(report)
            if not can_approve:
                st.caption("현재 상태에서는 승인할 수 없습니다. 근거·검산·변경 상태를 먼저 확인하세요.")
            if st.button("직접 확인하고 승인",key="fin_approve",disabled=not(can_approve and confirmed and reason.strip()),use_container_width=True):
                try:
                    st.session_state["fin_report"] = public_snapshot(pipeline.approve_report(report,reason=reason,confirmed=confirmed))
                    st.rerun()
                except Exception as exc:
                    notice_error(exc)

st.divider()
st.subheader("보고서 저장과 다시 열기")
st.caption("실제 실행 상태, 확인 사유와 입력 지문을 보고서로 저장합니다. 다시 연 보고서는 현재 입력과의 연결을 재검사합니다.")
report = st.session_state.get("fin_report")
if report:
    payload = pipeline.export_report(public_snapshot(report))
    st.session_state["fin_exported_report"] = payload
    st.download_button("검산 보고서 JSON 내려받기",payload,file_name=f"0_이영_{case_id}_검산보고서.json",mime="application/json",key="fin_report_download")
    with st.expander("보고서 상세 보기"):
        st.json(public_snapshot(report))
with st.expander("저장한 보고서 다시 열기"):
    uploaded = st.file_uploader("검산 보고서 JSON 파일",type=["json"],key="fin_report_upload")
    pasted = st.text_area("보고서 JSON 붙여넣기",key="fin_reopen_text",height=140)
    if st.button("보고서 다시 열기",key="fin_reopen",disabled=uploaded is None and not pasted.strip()):
        try:
            text = uploaded.getvalue().decode("utf-8") if uploaded is not None else pasted
            st.session_state["fin_reopened"] = public_snapshot(pipeline.reopen_report(text))
        except Exception as exc:
            notice_error(exc)
    if st.session_state.get("fin_reopened"):
        st.json(st.session_state["fin_reopened"])
        st.caption("불러온 기록은 새로운 사람 승인으로 처리하지 않습니다.")
