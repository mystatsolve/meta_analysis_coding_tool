#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
메타분석 PDF 코딩 앱
PDF 논문 → 평균/SD/Cohen's d/Hedges' g/서브그룹 자동 추출 → CSV 다운로드
지원 API: Anthropic Claude / OpenAI ChatGPT
"""

import sys, io as _io
# Windows 콘솔 ASCII 인코딩 오류 방지 — 반드시 다른 import 전에 실행
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

import streamlit as st
import json, math, base64, io, re
import pandas as pd
import matplotlib
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm

# ── 페이지 설정 ────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="메타분석 코딩 앱",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── 한국어 폰트 ────────────────────────────────────────────────────────────────
def setup_korean_font():
    for font in ["Malgun Gothic", "NanumGothic", "NanumBarunGothic", "AppleGothic"]:
        if font in {f.name for f in fm.fontManager.ttflist}:
            matplotlib.rcParams["font.family"] = font
            matplotlib.rcParams["axes.unicode_minus"] = False
            return font
    matplotlib.rcParams["axes.unicode_minus"] = False
    return None

KOREAN_FONT = setup_korean_font()

# ── API 제공자 & 모델 ──────────────────────────────────────────────────────────
PROVIDERS = {
    "🔵 Anthropic Claude": {
        "models": {
            "Claude Sonnet 4.6 (권장)":  "claude-sonnet-4-6",
            "Claude Opus 4.6 (고정확도)": "claude-opus-4-6",
            "Claude Haiku 4.5 (빠름)":   "claude-haiku-4-5-20251001",
        },
        "key_placeholder": "sk-ant-...",
        "key_help": "Anthropic Console (console.anthropic.com)",
        "pdf_method": "PDF 직접 전송 (네이티브 지원)",
    },
    "🟢 OpenAI ChatGPT": {
        "models": {
            "GPT-4.1 (최신·최고성능)": "gpt-4.1",
            "GPT-4o (권장)":           "gpt-4o",
            "GPT-4o mini (저비용)":    "gpt-4o-mini",
            "GPT-4 Turbo":             "gpt-4-turbo",
        },
        "key_placeholder": "sk-...",
        "key_help": "OpenAI Platform (platform.openai.com)",
        "pdf_method": "PDF → 이미지 변환 후 Vision 전송",
    },
}

# ── 추출 프롬프트 ──────────────────────────────────────────────────────────────
EXTRACTION_PROMPT = """
이 논문에서 메타분석(meta-analysis)에 필요한 정량 데이터를 추출해주세요.

**순수 JSON만 반환하세요** (설명 텍스트·마크다운 블록 없음).

JSON 구조:
{
  "study": {
    "authors": "성(Family name) et al. 또는 전체 저자명",
    "year": "발행연도(4자리)",
    "journal": "저널명",
    "title": "논문 제목",
    "n_TG": 실험/훈련군 n (정수),
    "n_CG": 통제/대조군 n (정수),
    "population": "연구대상 설명",
    "intervention": "중재 프로그램 설명",
    "duration": "훈련/개입 기간"
  },
  "outcomes": [
    {
      "outcome_kr": "결과변수명 한국어 (논문이 영어면 번역)",
      "outcome_en": "결과변수명 영어",
      "unit": "측정 단위 (예: kg, %, cm, mg, sec, reps)",
      "subgroup_kr": "서브그룹 카테고리 한국어 (예: 신체구성, 건강관련체력, 식이섭취, 심리적 변인 등)",
      "subgroup_en": "Subgroup category in English",
      "TG_pre_M":   실험군 사전 평균  (숫자 또는 null),
      "TG_pre_SD":  실험군 사전 SD   (숫자 또는 null),
      "TG_post_M":  실험군 사후 평균  (숫자 또는 null),
      "TG_post_SD": 실험군 사후 SD   (숫자 또는 null),
      "CG_pre_M":   통제군 사전 평균  (숫자 또는 null),
      "CG_pre_SD":  통제군 사전 SD   (숫자 또는 null),
      "CG_post_M":  통제군 사후 평균  (숫자 또는 null),
      "CG_post_SD": 통제군 사후 SD   (숫자 또는 null),
      "F_group":        집단 간 F값    (숫자 또는 null),
      "F_time":         시간 F값       (숫자 또는 null),
      "F_interaction":  상호작용 F값   (숫자 또는 null),
      "note": "통계 유의성 및 특이사항 (예: Time p<0.01; G×T p<0.05)"
    }
  ]
}

추출 지침:
1. 논문의 **모든 결과 테이블**에서 Pre/Post 평균(M)과 표준편차(SD)를 추출.
2. ± 기호 제거 후 숫자만 (예: 45.0±6.08 → M=45.0, SD=6.08).
3. 실험군(TG): 훈련군·실험군·운동군·EG·TG·치료군 등
   통제군(CG): 통제군·대조군·CG·비교군 등
4. F값의 *, ** 표시는 note에 포함 (예: "F=9.65, p<0.01").
5. 값 없으면 null. 측정치 없는 변수도 null로 포함.
6. 서브그룹은 논문 결과 섹션 구분을 따름.
"""

# ── PDF → 이미지 변환 (OpenAI Vision용) ───────────────────────────────────────
def pdf_to_images_b64(pdf_bytes: bytes, dpi: int = 120, max_pages: int = 30) -> list[str]:
    """pymupdf로 PDF 페이지를 PNG base64 리스트로 변환"""
    import fitz
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    images = []
    scale = dpi / 72
    mat = fitz.Matrix(scale, scale)
    for i, page in enumerate(doc):
        if i >= max_pages:
            break
        pix = page.get_pixmap(matrix=mat)
        images.append(base64.standard_b64encode(pix.tobytes("png")).decode("utf-8"))
    return images


# ── API 호출 ───────────────────────────────────────────────────────────────────
def analyze_with_claude(pdf_bytes: bytes, api_key: str, model_id: str) -> str:
    import anthropic
    client = anthropic.Anthropic(api_key=api_key)
    pdf_b64 = base64.standard_b64encode(pdf_bytes).decode("utf-8")
    resp = client.messages.create(
        model=model_id,
        max_tokens=8192,
        messages=[{
            "role": "user",
            "content": [
                {
                    "type": "document",
                    "source": {
                        "type": "base64",
                        "media_type": "application/pdf",
                        "data": pdf_b64,
                    },
                },
                {"type": "text", "text": EXTRACTION_PROMPT},
            ],
        }],
    )
    return resp.content[0].text


def _make_openai_client(api_key: str):
    """httpx 0.28+ proxies 충돌 우회: http_client 명시 전달"""
    import httpx
    from openai import OpenAI
    return OpenAI(api_key=api_key, http_client=httpx.Client())


def analyze_with_openai(pdf_bytes: bytes, api_key: str, model_id: str) -> str:
    client = _make_openai_client(api_key)

    # PDF → 이미지 → Vision (최대 20페이지, detail:auto로 토큰 절약)
    images = pdf_to_images_b64(pdf_bytes, dpi=150, max_pages=20)
    if not images:
        raise ValueError("PDF에서 이미지를 추출할 수 없습니다.")

    content: list = [{"type": "text", "text": EXTRACTION_PROMPT}]
    for img_b64 in images:
        content.append({
            "type": "image_url",
            "image_url": {
                "url": f"data:image/png;base64,{img_b64}",
                "detail": "high",
            },
        })

    resp = client.chat.completions.create(
        model=model_id,
        max_tokens=8192,
        messages=[{"role": "user", "content": content}],
    )

    choice = resp.choices[0]

    # 거절(refusal) 또는 빈 응답 처리
    if hasattr(choice.message, "refusal") and choice.message.refusal:
        raise ValueError(f"모델 거절 응답: {choice.message.refusal}")

    result = choice.message.content
    if not result:
        finish = choice.finish_reason
        raise ValueError(
            f"모델 응답이 비어있습니다. (finish_reason={finish})\n"
            "토큰 한도 초과 또는 모델이 해당 PDF 형식을 지원하지 않을 수 있습니다."
        )

    return result


# ── 공통 분석 진입점 ───────────────────────────────────────────────────────────
def analyze_pdf(pdf_bytes: bytes, provider: str, api_key: str, model_id: str) -> str:
    if "Claude" in provider:
        return analyze_with_claude(pdf_bytes, api_key, model_id)
    else:
        return analyze_with_openai(pdf_bytes, api_key, model_id)


# ── 효과 크기 계산 ─────────────────────────────────────────────────────────────
def calc_effects(outcomes: list, n_tg: int, n_cg: int):
    df_val = n_tg + n_cg - 2
    J = 1 - 3 / (4 * df_val - 1)
    for o in outcomes:
        vals = [o.get(k) for k in
                ["TG_pre_M", "TG_pre_SD", "TG_post_M",
                 "CG_pre_M", "CG_pre_SD", "CG_post_M"]]
        if any(v is None for v in vals):
            o.update(delta_TG=None, delta_CG=None,
                     SD_pooled_pre=None, cohen_d=None, hedges_g=None)
            continue
        try:
            tg_pre_m, tg_pre_sd, tg_post_m, cg_pre_m, cg_pre_sd, cg_post_m = vals
            delta_tg = tg_post_m - tg_pre_m
            delta_cg = cg_post_m - cg_pre_m
            sp = math.sqrt(((n_tg - 1) * tg_pre_sd ** 2 +
                            (n_cg - 1) * cg_pre_sd ** 2) / df_val)
            d = (delta_tg - delta_cg) / sp if sp > 0 else None
            g = d * J if d is not None else None
            o.update(
                delta_TG=round(delta_tg, 4), delta_CG=round(delta_cg, 4),
                SD_pooled_pre=round(sp, 2),
                cohen_d=round(d, 2) if d else None,
                hedges_g=round(g, 2) if g else None,
            )
        except Exception:
            o.update(delta_TG=None, delta_CG=None,
                     SD_pooled_pre=None, cohen_d=None, hedges_g=None)
    return outcomes, J, df_val


def to_dataframe(study: dict, outcomes: list) -> pd.DataFrame:
    auth = study.get("authors", "Unknown")
    last = auth.split(",")[0].strip().split()[-1]
    sid = f"{last}{study.get('year', '')}"
    rows = []
    for o in outcomes:
        rows.append({
            "study_id": sid, "저자": study.get("authors", ""),
            "발행연도": study.get("year", ""), "저널": study.get("journal", ""),
            "대상": study.get("population", ""),
            "outcome_kr": o.get("outcome_kr", ""), "outcome_en": o.get("outcome_en", ""),
            "단위": o.get("unit", ""),
            "subgroup_kr": o.get("subgroup_kr", ""), "subgroup_en": o.get("subgroup_en", ""),
            "n_TG": study.get("n_TG", ""), "n_CG": study.get("n_CG", ""),
            "TG_pre_M": o.get("TG_pre_M", ""),   "TG_pre_SD": o.get("TG_pre_SD", ""),
            "TG_post_M": o.get("TG_post_M", ""),  "TG_post_SD": o.get("TG_post_SD", ""),
            "CG_pre_M": o.get("CG_pre_M", ""),    "CG_pre_SD": o.get("CG_pre_SD", ""),
            "CG_post_M": o.get("CG_post_M", ""),  "CG_post_SD": o.get("CG_post_SD", ""),
            "delta_TG": o.get("delta_TG", ""),     "delta_CG": o.get("delta_CG", ""),
            "SD_pooled_pre": o.get("SD_pooled_pre", ""),
            "cohen_d": o.get("cohen_d", ""),       "hedges_g": o.get("hedges_g", ""),
            "F_집단": o.get("F_group", ""),        "F_시간": o.get("F_time", ""),
            "F_집단x시간": o.get("F_interaction", ""), "비고": o.get("note", ""),
        })
    return pd.DataFrame(rows)


def extract_json(text: str) -> str:
    m = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text)
    if m:
        return m.group(1).strip()
    s, e = text.find("{"), text.rfind("}")
    if s != -1 and e != -1:
        return text[s: e + 1]
    return text


def make_effect_chart(df: pd.DataFrame, font_name):
    d_df = df[df["cohen_d"].notna()].copy()
    d_df["cohen_d"] = pd.to_numeric(d_df["cohen_d"], errors="coerce")
    d_df = d_df.dropna(subset=["cohen_d"]).sort_values("cohen_d")
    if d_df.empty:
        return None
    n = len(d_df)
    fig, ax = plt.subplots(figsize=(9, max(4, n * 0.45)))
    colors = ["#F44336" if v < 0 else "#2196F3" for v in d_df["cohen_d"]]
    bars = ax.barh(d_df["outcome_kr"], d_df["cohen_d"], color=colors, height=0.6)
    ax.axvline(0, color="black", linewidth=0.8)
    for xv, ls in [(0.2, "--"), (0.5, "-."), (0.8, ":")]:
        for sign in [1, -1]:
            ax.axvline(sign * xv, color="gray", linewidth=0.6, linestyle=ls, alpha=0.5)
    for bar, val in zip(bars, d_df["cohen_d"]):
        xpos = bar.get_width() + 0.03 if val >= 0 else bar.get_width() - 0.03
        ax.text(xpos, bar.get_y() + bar.get_height() / 2,
                f"{val:.2f}", va="center", ha="left" if val >= 0 else "right", fontsize=8)
    ax.set_xlabel("Cohen's d", fontsize=10)
    ax.set_title("효과 크기 (Cohen's d)", fontsize=11, pad=10)
    ax.tick_params(axis="y", labelsize=9)
    plt.tight_layout()
    return fig


# ══════════════════════════════════════════════════════════════════════════════
#  UI
# ══════════════════════════════════════════════════════════════════════════════

# ── 사이드바 ───────────────────────────────────────────────────────────────────
with st.sidebar:
    st.header("⚙️ 설정")

    # 제공자 선택
    provider = st.radio("🏢 API 제공자", list(PROVIDERS.keys()), horizontal=False)
    pconf = PROVIDERS[provider]

    # API Key
    api_key = st.text_input(
        "🔑 API Key",
        type="password",
        placeholder=pconf["key_placeholder"],
        help=pconf["key_help"],
    )

    # 모델 선택
    model_label = st.selectbox("🤖 모델", list(pconf["models"].keys()))
    model_id = pconf["models"][model_label]

    st.caption(f"📄 PDF 처리: {pconf['pdf_method']}")

    # ── API 연결 테스트 ──────────────────────────────────────────────────────
    if api_key and st.button("🔌 API 연결 테스트", use_container_width=True):
        with st.spinner("연결 확인 중..."):
            try:
                if "Claude" in provider:
                    import anthropic
                    c = anthropic.Anthropic(api_key=api_key)
                    c.messages.create(
                        model=model_id, max_tokens=16,
                        messages=[{"role": "user", "content": "hi"}],
                    )
                else:
                    c = _make_openai_client(api_key)
                    c.chat.completions.create(
                        model=model_id, max_tokens=16,
                        messages=[{"role": "user", "content": "hi"}],
                    )
                st.success("✅ 연결 성공!")
            except Exception as _e:
                st.error(f"[오류]{_e}")

    st.divider()
    st.markdown("### 📐 효과 크기 공식")
    st.markdown("**Cohen's d (Morris, 2008)**")
    st.latex(r"d = \frac{\Delta_{TG} - \Delta_{CG}}{SD_{pooled,pre}}")
    st.markdown("**Hedges' g (소표본 보정)**")
    st.latex(r"g = d \times \left(1-\frac{3}{4df-1}\right)")

    st.divider()
    st.markdown("### 💡 Cohen's d 기준")
    st.markdown(
        "| 값 | 해석 |\n|---|---|\n"
        "| < 0.2 | 효과 없음 |\n| 0.2–0.5 | 소효과 |\n"
        "| 0.5–0.8 | 중간효과 |\n| ≥ 0.8 | 대효과 |"
    )
    if KOREAN_FONT:
        st.caption(f"✅ 한국어 폰트: {KOREAN_FONT}")

# ── 메인 ──────────────────────────────────────────────────────────────────────
st.title("📊 메타분석 PDF 코딩 앱")
st.markdown(
    "논문 PDF를 업로드하면 **평균, 표준편차, Cohen's d, Hedges' g, 서브그룹**을 "
    "자동 추출하여 CSV로 저장합니다.  \n"
    "**Anthropic Claude** 또는 **OpenAI ChatGPT** 중 원하는 API를 선택하세요."
)

# 현재 선택된 제공자 표시
badge_color = "#1565C0" if "Claude" in provider else "#1B5E20"
st.markdown(
    f'<div style="background:{badge_color};color:white;padding:6px 14px;'
    f'border-radius:6px;display:inline-block;font-size:0.9rem;">'
    f'{provider} · {model_label}</div>',
    unsafe_allow_html=True,
)
st.write("")

uploaded = st.file_uploader("📄 논문 PDF 업로드 (최대 32 MB)", type="pdf")

if not uploaded:
    st.info("👆 분석할 논문 PDF를 업로드해주세요.")
    with st.expander("💡 사용법"):
        st.markdown("""
1. **사이드바**에서 API 제공자(Claude / ChatGPT)와 API Key 선택
2. **PDF 업로드** → **분석 시작**
3. 표본 크기(n) 확인·수정 → Cohen's d 자동 계산
4. 결과 확인 → **CSV 다운로드**

| 제공자 | PDF 처리 방식 |
|--------|-------------|
| Anthropic Claude | PDF 원본 직접 전송 (가장 정확) |
| OpenAI ChatGPT | PDF → 페이지 이미지 → Vision API |
        """)
    st.stop()

file_mb = uploaded.size / (1024 * 1024)
if file_mb > 32:
    st.error(f"파일 {file_mb:.1f} MB — 32 MB 초과.")
    st.stop()

st.success(f"✅ **{uploaded.name}** ({file_mb:.1f} MB)")

if not api_key:
    st.warning("⬅️ 사이드바에서 API Key를 입력해주세요.")
    st.stop()

# ── 버튼 ──────────────────────────────────────────────────────────────────────
btn_col, reset_col, _ = st.columns([1, 1, 4])
run_btn   = btn_col.button("🔍 분석 시작", type="primary", use_container_width=True)
reset_btn = reset_col.button("🔄 초기화", use_container_width=True)

if reset_btn:
    for k in ["extracted", "study", "outcomes", "raw_json", "used_provider"]:
        st.session_state.pop(k, None)
    st.rerun()

if run_btn:
    for k in ["extracted", "study", "outcomes", "raw_json", "used_provider"]:
        st.session_state.pop(k, None)

    pdf_bytes = uploaded.read()
    progress = st.progress(0, text="분석 준비 중...")
    status = st.empty()

    try:
        if "Claude" in provider:
            progress.progress(15, text="Claude가 PDF를 읽는 중...")
        else:
            progress.progress(10, text="PDF를 이미지로 변환 중...")
            progress.progress(25, text=f"{model_label} Vision에 전송 중...")

        raw_text = analyze_pdf(pdf_bytes, provider, api_key, model_id)

        progress.progress(80, text="JSON 파싱 중...")
        json_str = extract_json(raw_text)
        data = json.loads(json_str)

        st.session_state.update(
            extracted=True,
            study=data["study"],
            outcomes=data["outcomes"],
            raw_json=raw_text,
            used_provider=provider,
        )
        progress.progress(100, text="완료!")
        status.success("✅ 분석 완료!")

    except json.JSONDecodeError as e:
        progress.empty()
        st.error(f"JSON 파싱 오류: {e}")
        with st.expander("AI 원본 응답"):
            st.code(raw_text, language="json")
        st.stop()
    except Exception as e:
        progress.empty()
        err_str = str(e)
        if "api_key" in err_str.lower() or "authentication" in err_str.lower() or "401" in err_str:
            st.error("[오류]API Key가 잘못되었거나 권한이 없습니다. Key를 확인해주세요.")
        elif "rate" in err_str.lower() or "429" in err_str:
            st.error("[오류]API 요청 한도 초과. 잠시 후 다시 시도해주세요.")
        elif "model" in err_str.lower() and ("not found" in err_str.lower() or "does not exist" in err_str.lower()):
            st.error(f"[오류]모델 '{model_id}'을 찾을 수 없습니다. 다른 모델을 선택해주세요.")
        elif "context" in err_str.lower() or "token" in err_str.lower() or "length" in err_str.lower():
            st.error("[오류]PDF가 너무 깁니다. 페이지 수를 줄이거나 다른 모델을 사용해보세요.")
        else:
            st.error(f"[오류]오류 발생: {e}")
            with st.expander("오류 상세 내용"):
                st.exception(e)
        st.stop()

# ── 결과 표시 ──────────────────────────────────────────────────────────────────
if not st.session_state.get("extracted"):
    st.stop()

study    = st.session_state["study"]
outcomes = st.session_state["outcomes"]
used_pv  = st.session_state.get("used_provider", "")

st.divider()

# 어떤 API로 분석했는지 표시
st.caption(f"분석에 사용된 API: **{used_pv}**")

st.subheader("📋 연구 정보")
m1, m2, m3, m4 = st.columns(4)
m1.metric("저자",     study.get("authors", "N/A"))
m2.metric("연도",     study.get("year",    "N/A"))
m3.metric("훈련군 n", study.get("n_TG",    "N/A"))
m4.metric("통제군 n", study.get("n_CG",    "N/A"))

with st.expander("📝 연구 상세 정보"):
    for label, key in [("제목","title"),("저널","journal"),
                        ("대상","population"),("중재","intervention"),("기간","duration")]:
        v = study.get(key, "")
        if v:
            st.markdown(f"**{label}:** {v}")

# ── n값 수정 ───────────────────────────────────────────────────────────────────
st.subheader("👥 표본 크기 확인 / 수정")
st.caption("AI가 잘못 읽었을 경우 직접 수정하세요. 수정하면 Cohen's d가 즉시 재계산됩니다.")
nc1, nc2, _ = st.columns([1, 1, 3])
n_tg = nc1.number_input("훈련군(TG) n", value=max(1, int(study.get("n_TG") or 1)), min_value=1)
n_cg = nc2.number_input("통제군(CG) n", value=max(1, int(study.get("n_CG") or 1)), min_value=1)

df_val = n_tg + n_cg - 2
J_val  = 1 - 3 / (4 * df_val - 1)
st.caption(f"df = {df_val},  Hedges' J = {J_val:.4f}")

outcomes_calc, _, _ = calc_effects([dict(o) for o in outcomes], n_tg, n_cg)
df_result = to_dataframe({**study, "n_TG": n_tg, "n_CG": n_cg}, outcomes_calc)

# ── 결과 테이블 ────────────────────────────────────────────────────────────────
st.divider()
st.subheader(f"📊 추출 결과 — {len(outcomes_calc)}개 변수")

# 서브그룹 필터
subgroups = ["전체"] + sorted(df_result["subgroup_kr"].dropna().unique().tolist())
sel_sg    = st.selectbox("서브그룹 필터", subgroups)
disp      = df_result if sel_sg == "전체" else df_result[df_result["subgroup_kr"] == sel_sg]

# 컬럼 범위 토글
_default_cols = [
    "outcome_kr", "subgroup_kr", "단위",
    "TG_pre_M", "TG_pre_SD", "TG_post_M", "TG_post_SD",
    "CG_pre_M", "CG_pre_SD", "CG_post_M", "CG_post_SD",
    "delta_TG", "delta_CG", "cohen_d", "hedges_g", "비고",
]
_all_cols = list(disp.columns)

# ── 열 선택 (멀티셀렉트) ──────────────────────────────────────────────────────
_sel_cols = st.multiselect(
    "📋 열(Column) 선택 — 미선택 시 기본 열 전체 저장",
    options=_all_cols,
    default=[],
    placeholder="저장할 열을 선택하세요 (복수 선택 가능)...",
    key=f"col_select_{sel_sg}",
)
_show_cols = _sel_cols if _sel_cols else [c for c in _default_cols if c in _all_cols]

st.caption("💡 **행 클릭** → 행 선택(복수 가능) · 선택한 행+열 데이터만 CSV로 저장 · 미선택 시 전체 저장")

# ── 행 직접 선택 테이블 ────────────────────────────────────────────────────────
event = st.dataframe(
    disp[_show_cols],
    use_container_width=True,
    height=420,
    on_select="rerun",
    selection_mode="multi-row",
    key=f"result_table_{sel_sg}_{str(_sel_cols)}",
)

_sel_rows = event.selection.rows   # list[int]

# 내보낼 데이터 결정
export_df = disp[_show_cols].copy()
if _sel_rows:
    export_df = export_df.iloc[_sel_rows]

n_ok = df_result["cohen_d"].notna().sum()
_row_info = f"{len(export_df)}행" if _sel_rows else f"전체 {len(disp)}행"
_col_info = f"{len(_show_cols)}열 (선택)" if _sel_cols else f"{len(_show_cols)}열 (기본)"
st.caption(f"Cohen's d 계산됨: {n_ok}/{len(df_result)}개  ·  CSV 저장 예정: **{_row_info} × {_col_info}**")

# ── 차트 ───────────────────────────────────────────────────────────────────────
st.divider()
st.subheader("📈 Cohen's d 효과 크기 분포")
fig = make_effect_chart(df_result, KOREAN_FONT)
if fig:
    st.pyplot(fig, use_container_width=True)
    plt.close(fig)
else:
    st.info("계산 가능한 Cohen's d가 없습니다.")

# ── CSV 다운로드 ───────────────────────────────────────────────────────────────
st.divider()
csv_bytes = export_df.to_csv(index=False, encoding="utf-8-sig").encode("utf-8-sig")
out_fname = re.sub(r"[^\w가-힣.\- ]", "_", uploaded.name).replace(".pdf", "_meta_coding.csv")

dl1, _ = st.columns([1, 4])
dl1.download_button(
    "⬇️ CSV 다운로드",
    data=csv_bytes, file_name=out_fname,
    mime="text/csv", type="primary", use_container_width=True,
)

# ── 원본 JSON ──────────────────────────────────────────────────────────────────
with st.expander("🔧 AI 원본 JSON 응답 보기"):
    st.code(st.session_state.get("raw_json", ""), language="json")
