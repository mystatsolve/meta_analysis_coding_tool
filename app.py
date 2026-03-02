#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
==============================================================================
메타분석 PDF 코딩 앱 (Meta-Analysis PDF Coding App)
==============================================================================
기능 요약:
  - 논문 PDF를 업로드하면 AI(Claude 또는 ChatGPT)가 자동으로 통계 데이터를 추출
  - 추출 항목: 평균(M), 표준편차(SD), 표본 크기(n), F값, 서브그룹 등
  - Cohen's d (Morris, 2008) 및 Hedges' g 효과 크기를 자동 계산
  - 결과를 인터랙티브 표로 보여주고 CSV로 다운로드
  - 지원 API: Anthropic Claude / OpenAI ChatGPT
==============================================================================
"""

# ── [1] 표준 라이브러리 import ─────────────────────────────────────────────────
import sys          # 파이썬 인터프리터 관련 기능 (stdout 인코딩 설정 등)
import io as _io    # 바이트/문자 스트림 처리 (충돌 방지용 별칭 _io로 import)

# ── [2] Windows 콘솔 인코딩 강제 UTF-8 설정 ────────────────────────────────────
# 이유: Windows 기본 콘솔 인코딩은 cp949(EUC-KR) 또는 ASCII여서
#       한국어·이모지 포함 오류 메시지 출력 시 UnicodeEncodeError 발생.
#       reconfigure()로 stdout/stderr를 UTF-8로 전환하여 방지.
#       errors="replace": 인코딩 불가 문자는 '?'로 대체 (앱 중단 방지)
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# ── [3] 외부 라이브러리 import ────────────────────────────────────────────────
import streamlit as st          # 웹 앱 프레임워크 (UI 컴포넌트 제공)
import json                     # JSON 문자열 파싱 및 직렬화
import math                     # sqrt 등 수학 함수 (효과 크기 계산에 사용)
import base64                   # PDF/이미지를 base64 문자열로 인코딩 (API 전송용)
import io                       # BytesIO: 메모리 상의 파일 스트림 처리
import re                       # 정규식: JSON 추출, 파일명 정제에 사용
import pandas as pd             # DataFrame: 표 형태 데이터 처리 및 CSV 생성
import matplotlib               # 그래프 기본 설정 (폰트, 마이너스 기호 등)
import matplotlib.pyplot as plt # 실제 그래프 그리기 (barh 차트)
import matplotlib.font_manager as fm  # 시스템 폰트 목록 조회 (한국어 폰트 탐색)


# ══════════════════════════════════════════════════════════════════════════════
# [A] 페이지 기본 설정
# ══════════════════════════════════════════════════════════════════════════════
st.set_page_config(
    page_title="메타분석 코딩 앱",   # 브라우저 탭 제목
    page_icon="📊",                  # 브라우저 탭 아이콘 (favicon)
    layout="wide",                   # 화면 전체 너비 사용 (wide 레이아웃)
    initial_sidebar_state="expanded",# 앱 시작 시 사이드바 펼쳐진 상태로 시작
)


# ══════════════════════════════════════════════════════════════════════════════
# [B] 한국어 폰트 설정
# ══════════════════════════════════════════════════════════════════════════════
def setup_korean_font():
    """
    matplotlib 차트에서 한국어가 깨지지 않도록 폰트를 설정하는 함수.
    OS별로 설치된 폰트가 다르므로 우선순위 목록에서 첫 번째 이용 가능한 폰트를 사용.
    우선순위: Malgun Gothic(Windows) > NanumGothic > NanumBarunGothic > AppleGothic(macOS)
    반환값: 설정된 폰트 이름 문자열, 없으면 None
    """
    # 시스템에 설치된 모든 폰트 이름을 집합(set)으로 수집
    available = {f.name for f in fm.fontManager.ttflist}

    for font in ["Malgun Gothic", "NanumGothic", "NanumBarunGothic", "AppleGothic"]:
        if font in available:                          # 해당 폰트가 시스템에 존재하면
            matplotlib.rcParams["font.family"] = font  # matplotlib 기본 폰트로 설정
            matplotlib.rcParams["axes.unicode_minus"] = False  # '-' 기호 깨짐 방지
            return font  # 설정된 폰트 이름 반환 (사이드바에 표시용)

    # 한국어 폰트를 찾지 못한 경우에도 마이너스 깨짐만은 방지
    matplotlib.rcParams["axes.unicode_minus"] = False
    return None  # 폰트 설정 실패 반환

# 모듈 로드 시 1회 실행 → 전역 변수로 폰트 이름 저장
KOREAN_FONT = setup_korean_font()


# ══════════════════════════════════════════════════════════════════════════════
# [C] API 제공자 및 모델 설정
# ══════════════════════════════════════════════════════════════════════════════
# PROVIDERS: 딕셔너리 형태로 제공자별 설정을 한 곳에서 관리
#   - models: UI에 표시할 모델 이름 → 실제 API 모델 ID 매핑
#   - key_placeholder: API Key 입력 필드에 표시할 힌트 텍스트
#   - key_help: API Key 발급 안내 링크
#   - pdf_method: PDF 처리 방식 설명 (사용자에게 안내용)
PROVIDERS = {
    "🔵 Anthropic Claude": {
        "models": {
            # Claude Sonnet 4.6: 속도와 정확도의 균형, 일반적인 사용에 권장
            "Claude Sonnet 4.6 (권장)":  "claude-sonnet-4-6",
            # Claude Opus 4.6: 최고 정확도, 복잡한 논문 분석에 적합 (느리고 비용 높음)
            "Claude Opus 4.6 (고정확도)": "claude-opus-4-6",
            # Claude Haiku 4.5: 가장 빠르고 저렴, 간단한 논문에 적합
            "Claude Haiku 4.5 (빠름)":   "claude-haiku-4-5-20251001",
        },
        "key_placeholder": "sk-ant-...",                        # Anthropic API Key 형식
        "key_help": "Anthropic Console (console.anthropic.com)",# 발급 안내
        "pdf_method": "PDF 직접 전송 (네이티브 지원)",            # Claude는 PDF 원본 지원
    },
    "🟢 OpenAI ChatGPT": {
        "models": {
            # GPT-4.1: 2025년 출시 최신 모델, 최고 성능 (Vision 지원)
            "GPT-4.1 (최신·최고성능)": "gpt-4.1",
            # GPT-4o: 멀티모달(Vision) 지원, 속도와 성능 균형
            "GPT-4o (권장)":           "gpt-4o",
            # GPT-4o mini: 저비용 경량 모델, 빠른 처리
            "GPT-4o mini (저비용)":    "gpt-4o-mini",
            # GPT-4 Turbo: 이전 세대 최고 성능 모델
            "GPT-4 Turbo":             "gpt-4-turbo",
        },
        "key_placeholder": "sk-...",                              # OpenAI API Key 형식
        "key_help": "OpenAI Platform (platform.openai.com)",      # 발급 안내
        "pdf_method": "PDF → 이미지 변환 후 Vision 전송",          # OpenAI는 PDF 미지원, 변환 필요
    },
}


# ══════════════════════════════════════════════════════════════════════════════
# [D] AI 추출 프롬프트
# ══════════════════════════════════════════════════════════════════════════════
# AI에게 전달하는 지시문(prompt). 이 텍스트가 Claude/ChatGPT에 전송되어
# 논문에서 추출할 데이터 구조와 추출 규칙을 정의함.
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


# ══════════════════════════════════════════════════════════════════════════════
# [E] PDF → 이미지 변환 함수 (OpenAI Vision 전송용)
# ══════════════════════════════════════════════════════════════════════════════
def pdf_to_images_b64(pdf_bytes: bytes, dpi: int = 120, max_pages: int = 30) -> list[str]:
    """
    PDF 바이너리 데이터를 페이지별 PNG 이미지로 변환하여 base64 인코딩 문자열 목록 반환.

    이유: OpenAI API는 PDF를 직접 받지 못하므로 각 페이지를 이미지로 변환 후 전송.
    pymupdf(fitz) 라이브러리 사용 - 고품질 PDF 렌더링 지원.

    매개변수:
        pdf_bytes (bytes): PDF 파일의 원시 바이너리 데이터
        dpi (int): 렌더링 해상도. 72dpi=화면 기본, 150dpi=고품질 (기본값 120)
        max_pages (int): 변환할 최대 페이지 수. 너무 많으면 API 토큰 초과 위험

    반환값:
        list[str]: 각 페이지의 base64 PNG 문자열 목록
    """
    import fitz  # pymupdf: PDF 처리 라이브러리 (lazy import - 필요할 때만 로드)

    # PDF 바이트 스트림을 열어 pymupdf Document 객체 생성
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")

    images = []  # 변환된 base64 이미지를 담을 리스트

    # DPI 기반 스케일 계산: PDF 기본 단위는 72pt/inch
    # 예) dpi=150이면 scale=150/72≈2.08 → 원본의 2배 크기로 렌더링
    scale = dpi / 72
    mat = fitz.Matrix(scale, scale)  # x, y 방향 동일 배율의 변환 행렬 생성

    for i, page in enumerate(doc):  # 각 페이지를 순서대로 처리
        if i >= max_pages:          # 최대 페이지 수 초과 시 반복 중단
            break

        # 페이지를 지정된 해상도로 픽셀맵(이미지)으로 변환
        pix = page.get_pixmap(matrix=mat)

        # PNG 바이트로 변환 후 base64 인코딩 → UTF-8 문자열로 디코딩
        # standard_b64encode: URL-safe가 아닌 표준 base64 알파벳 사용
        images.append(base64.standard_b64encode(pix.tobytes("png")).decode("utf-8"))

    return images  # 모든 페이지의 base64 이미지 리스트 반환


# ══════════════════════════════════════════════════════════════════════════════
# [F] API 호출 함수
# ══════════════════════════════════════════════════════════════════════════════

def analyze_with_claude(pdf_bytes: bytes, api_key: str, model_id: str) -> str:
    """
    Anthropic Claude API를 호출하여 PDF에서 메타분석 데이터를 추출.

    Claude는 PDF를 네이티브로 지원하므로 변환 없이 원본 PDF를 직접 전송.
    'document' 콘텐츠 타입으로 base64 인코딩된 PDF를 전달.

    매개변수:
        pdf_bytes (bytes): PDF 파일 원시 바이너리
        api_key (str): Anthropic API 키 (sk-ant-... 형식)
        model_id (str): 사용할 Claude 모델 ID (예: "claude-sonnet-4-6")

    반환값:
        str: AI가 반환한 JSON 형식의 텍스트 응답
    """
    import anthropic  # Anthropic 공식 Python SDK (lazy import)

    # API 키로 Anthropic 클라이언트 초기화
    client = anthropic.Anthropic(api_key=api_key)

    # PDF 바이너리를 base64 문자열로 인코딩 (API 전송 형식)
    pdf_b64 = base64.standard_b64encode(pdf_bytes).decode("utf-8")

    # Claude Messages API 호출
    resp = client.messages.create(
        model=model_id,       # 사용할 Claude 모델
        max_tokens=8192,      # 최대 출력 토큰 수 (긴 JSON 응답을 위해 충분히 설정)
        messages=[{
            "role": "user",   # 사용자 메시지로 전송
            "content": [
                {
                    # PDF 문서 콘텐츠 블록: Claude 전용 document 타입
                    "type": "document",
                    "source": {
                        "type": "base64",                  # base64 인코딩 데이터
                        "media_type": "application/pdf",   # MIME 타입: PDF
                        "data": pdf_b64,                   # 인코딩된 PDF 데이터
                    },
                },
                # 추출 지시 프롬프트를 텍스트 블록으로 추가
                {"type": "text", "text": EXTRACTION_PROMPT},
            ],
        }],
    )

    # 응답에서 첫 번째 콘텐츠 블록의 텍스트 추출
    return resp.content[0].text


def _make_openai_client(api_key: str):
    """
    OpenAI 클라이언트를 안전하게 생성하는 헬퍼 함수.

    문제 배경:
        httpx 0.28.0 이후 버전에서 'proxies' 매개변수가 제거됨.
        일부 openai SDK 버전이 내부적으로 httpx에 proxies를 전달하려다
        'Client.__init__() got an unexpected keyword argument proxies' 오류 발생.

    해결책:
        httpx.Client()를 직접 생성하여 OpenAI에 전달 → SDK가 httpx를
        자체 초기화하지 않아 proxies 충돌 우회.

    매개변수:
        api_key (str): OpenAI API 키 (sk-... 형식)

    반환값:
        OpenAI: 초기화된 OpenAI 클라이언트 인스턴스
    """
    import httpx          # HTTP 클라이언트 라이브러리 (openai SDK 내부에서 사용)
    from openai import OpenAI  # OpenAI 공식 Python SDK

    # httpx.Client()를 명시적으로 생성하여 http_client로 전달
    return OpenAI(api_key=api_key, http_client=httpx.Client())


def analyze_with_openai(pdf_bytes: bytes, api_key: str, model_id: str) -> str:
    """
    OpenAI ChatGPT Vision API를 호출하여 PDF에서 메타분석 데이터를 추출.

    OpenAI는 PDF 직접 처리를 지원하지 않으므로:
    1. pymupdf로 PDF 각 페이지를 PNG 이미지로 변환
    2. base64 인코딩 후 image_url 콘텐츠 타입으로 Vision API에 전송

    매개변수:
        pdf_bytes (bytes): PDF 파일 원시 바이너리
        api_key (str): OpenAI API 키 (sk-... 형식)
        model_id (str): 사용할 GPT 모델 ID (예: "gpt-4o")

    반환값:
        str: AI가 반환한 JSON 형식의 텍스트 응답

    예외:
        ValueError: PDF 이미지 추출 실패, 모델 거절, 빈 응답 등
    """
    # httpx 충돌 우회 함수를 통해 안전한 OpenAI 클라이언트 생성
    client = _make_openai_client(api_key)

    # PDF → PNG 이미지 변환 (최대 20페이지, 150dpi 고해상도)
    # max_pages=20: 너무 많은 이미지는 토큰 초과 위험 → 20페이지로 제한
    # dpi=150: 논문 표/수식이 선명하게 보이는 해상도
    images = pdf_to_images_b64(pdf_bytes, dpi=150, max_pages=20)

    if not images:  # 이미지 변환에 실패한 경우 (빈 PDF 등)
        raise ValueError("PDF에서 이미지를 추출할 수 없습니다.")

    # 메시지 콘텐츠 구성: 텍스트 프롬프트 + 이미지들
    content: list = [{"type": "text", "text": EXTRACTION_PROMPT}]  # 프롬프트 먼저

    for img_b64 in images:  # 각 페이지 이미지를 순서대로 추가
        content.append({
            "type": "image_url",     # OpenAI Vision API의 이미지 콘텐츠 타입
            "image_url": {
                # data URI 형식: "data:[미디어타입];base64,[데이터]"
                "url": f"data:image/png;base64,{img_b64}",
                # detail="high": 고해상도 분석 모드 → 표, 수식 등 세부 내용 인식
                # "auto": 자동 선택, "low": 저해상도 (저비용)
                "detail": "high",
            },
        })

    # OpenAI Chat Completions API 호출
    resp = client.chat.completions.create(
        model=model_id,    # 사용할 GPT 모델 (gpt-4o, gpt-4.1 등)
        max_tokens=8192,   # 최대 출력 토큰 수 (긴 JSON을 위해 충분히 설정)
        messages=[{"role": "user", "content": content}],  # 사용자 메시지
    )

    # 응답에서 첫 번째 선택지(choice) 추출
    choice = resp.choices[0]

    # 모델이 요청을 거절한 경우 처리 (콘텐츠 정책 위반 등)
    if hasattr(choice.message, "refusal") and choice.message.refusal:
        raise ValueError(f"모델 거절 응답: {choice.message.refusal}")

    # 응답 텍스트 추출
    result = choice.message.content

    if not result:  # 응답이 비어있는 경우 (토큰 초과 등)
        finish = choice.finish_reason  # 종료 이유 확인 (length=토큰초과, stop=정상 등)
        raise ValueError(
            f"모델 응답이 비어있습니다. (finish_reason={finish})\n"
            "토큰 한도 초과 또는 모델이 해당 PDF 형식을 지원하지 않을 수 있습니다."
        )

    return result  # JSON 텍스트 반환


# ══════════════════════════════════════════════════════════════════════════════
# [G] 공통 분석 진입점
# ══════════════════════════════════════════════════════════════════════════════
def analyze_pdf(pdf_bytes: bytes, provider: str, api_key: str, model_id: str) -> str:
    """
    선택된 API 제공자에 따라 적절한 분석 함수로 라우팅하는 디스패처.

    매개변수:
        pdf_bytes (bytes): PDF 파일 바이너리
        provider (str): 선택된 제공자 이름 ("🔵 Anthropic Claude" 또는 "🟢 OpenAI ChatGPT")
        api_key (str): 해당 제공자의 API 키
        model_id (str): 사용할 모델 ID

    반환값:
        str: AI 응답 텍스트 (JSON 형식)
    """
    if "Claude" in provider:         # 제공자 이름에 "Claude"가 포함되면
        return analyze_with_claude(pdf_bytes, api_key, model_id)  # Claude API 사용
    else:                            # 그 외 (OpenAI ChatGPT)
        return analyze_with_openai(pdf_bytes, api_key, model_id)  # OpenAI API 사용


# ══════════════════════════════════════════════════════════════════════════════
# [H] 효과 크기 계산 함수
# ══════════════════════════════════════════════════════════════════════════════
def calc_effects(outcomes: list, n_tg: int, n_cg: int):
    """
    각 결과 변수에 대해 Cohen's d와 Hedges' g 효과 크기를 계산.

    사용 공식 (Morris, 2008):
        Cohen's d = (Δ_TG - Δ_CG) / SD_pooled_pre
            Δ = post_M - pre_M (변화량)
            SD_pooled_pre = sqrt(((n_TG-1)*SD_TG_pre² + (n_CG-1)*SD_CG_pre²) / df)
            df = n_TG + n_CG - 2

        Hedges' g = d × J
            J = 1 - 3/(4×df - 1)  (소표본 보정 계수)

    매개변수:
        outcomes (list): AI 추출 결과 딕셔너리 목록 (각 결과 변수 정보)
        n_tg (int): 훈련군(실험군) 표본 크기
        n_cg (int): 통제군 표본 크기

    반환값:
        tuple: (업데이트된 outcomes 리스트, Hedges' J 보정값, 자유도 df)
    """
    df_val = n_tg + n_cg - 2          # 자유도 계산: 두 집단 합산 표본-2
    J = 1 - 3 / (4 * df_val - 1)      # Hedges' g 소표본 보정 계수 J

    for o in outcomes:  # 각 결과 변수(행)에 대해 반복

        # 효과 크기 계산에 필요한 6개 값 추출
        vals = [o.get(k) for k in
                ["TG_pre_M", "TG_pre_SD", "TG_post_M",   # 실험군 사전/후 M, 사전 SD
                 "CG_pre_M", "CG_pre_SD", "CG_post_M"]]  # 통제군 사전/후 M, 사전 SD

        if any(v is None for v in vals):  # 하나라도 결측값이면 계산 불가
            # 모든 효과 크기 관련 필드를 None으로 설정
            o.update(delta_TG=None, delta_CG=None,
                     SD_pooled_pre=None, cohen_d=None, hedges_g=None)
            continue  # 다음 결과 변수로 이동

        try:
            # 6개 값을 개별 변수로 언패킹
            tg_pre_m, tg_pre_sd, tg_post_m, cg_pre_m, cg_pre_sd, cg_post_m = vals

            # 변화량(Δ) 계산: 사후 - 사전
            delta_tg = tg_post_m - tg_pre_m   # 실험군 변화량
            delta_cg = cg_post_m - cg_pre_m   # 통제군 변화량

            # 사전 측정치 기반 합동 표준편차(pooled SD) 계산
            sp = math.sqrt(
                ((n_tg - 1) * tg_pre_sd ** 2 +   # 실험군 분산 가중 합산
                 (n_cg - 1) * cg_pre_sd ** 2) /   # 통제군 분산 가중 합산
                df_val                             # 자유도로 나눔
            )

            # Cohen's d 계산: sp=0이면 계산 불가 (0으로 나눔 방지)
            d = (delta_tg - delta_cg) / sp if sp > 0 else None

            # Hedges' g 계산: d에 소표본 보정 계수 J 곱하기
            g = d * J if d is not None else None

            # 계산 결과를 결과 변수 딕셔너리에 추가 (소수점 정리)
            o.update(
                delta_TG=round(delta_tg, 4),          # 실험군 변화량 (소수 4자리)
                delta_CG=round(delta_cg, 4),          # 통제군 변화량
                SD_pooled_pre=round(sp, 2),           # 합동 SD (소수 2자리)
                cohen_d=round(d, 2) if d else None,   # Cohen's d (소수 2자리)
                hedges_g=round(g, 2) if g else None,  # Hedges' g (소수 2자리)
            )

        except Exception:  # 예상치 못한 오류(타입 오류, 음수 sqrt 등) 처리
            o.update(delta_TG=None, delta_CG=None,
                     SD_pooled_pre=None, cohen_d=None, hedges_g=None)

    return outcomes, J, df_val  # 업데이트된 결과 목록과 보조 통계값 반환


# ══════════════════════════════════════════════════════════════════════════════
# [I] DataFrame 생성 함수
# ══════════════════════════════════════════════════════════════════════════════
def to_dataframe(study: dict, outcomes: list) -> pd.DataFrame:
    """
    연구 정보(study)와 결과 목록(outcomes)을 합쳐 CSV 형태의 DataFrame으로 변환.
    각 결과 변수(outcome)가 하나의 행(row)이 되며, 연구 정보는 모든 행에 반복.

    매개변수:
        study (dict): AI가 추출한 연구 기본 정보 (저자, 연도, 저널 등)
        outcomes (list): 효과 크기가 계산된 결과 변수 목록

    반환값:
        pd.DataFrame: 메타분석 코딩 결과 테이블
    """
    auth = study.get("authors", "Unknown")          # 저자명 추출
    last = auth.split(",")[0].strip().split()[-1]   # 첫 번째 저자의 성(last name) 추출
    # study_id: "제1저자성+연도" 형식 (예: Song2013)
    sid = f"{last}{study.get('year', '')}"

    rows = []  # 각 결과 변수에 해당하는 행을 담을 리스트

    for o in outcomes:  # 각 결과 변수(outcome)마다 1개 행 생성
        rows.append({
            # ── 연구 기본 정보 (모든 행 동일) ──────────────────────────────
            "study_id":  sid,                           # 식별 코드 (예: Song2013)
            "저자":      study.get("authors", ""),      # 전체 저자명
            "발행연도":  study.get("year", ""),          # 4자리 연도
            "저널":      study.get("journal", ""),       # 저널명
            "대상":      study.get("population", ""),    # 연구 대상 설명

            # ── 결과 변수 정보 ────────────────────────────────────────────
            "outcome_kr":   o.get("outcome_kr", ""),   # 결과 변수명 (한국어)
            "outcome_en":   o.get("outcome_en", ""),   # 결과 변수명 (영어)
            "단위":         o.get("unit", ""),          # 측정 단위 (kg, %, cm 등)
            "subgroup_kr":  o.get("subgroup_kr", ""),  # 서브그룹 (한국어)
            "subgroup_en":  o.get("subgroup_en", ""),  # 서브그룹 (영어)

            # ── 표본 크기 ─────────────────────────────────────────────────
            "n_TG": study.get("n_TG", ""),  # 실험군 표본 크기
            "n_CG": study.get("n_CG", ""),  # 통제군 표본 크기

            # ── 기술통계 (사전/사후 평균, SD) ────────────────────────────
            "TG_pre_M":   o.get("TG_pre_M", ""),    # 실험군 사전 평균
            "TG_pre_SD":  o.get("TG_pre_SD", ""),   # 실험군 사전 SD
            "TG_post_M":  o.get("TG_post_M", ""),   # 실험군 사후 평균
            "TG_post_SD": o.get("TG_post_SD", ""),  # 실험군 사후 SD
            "CG_pre_M":   o.get("CG_pre_M", ""),    # 통제군 사전 평균
            "CG_pre_SD":  o.get("CG_pre_SD", ""),   # 통제군 사전 SD
            "CG_post_M":  o.get("CG_post_M", ""),   # 통제군 사후 평균
            "CG_post_SD": o.get("CG_post_SD", ""),  # 통제군 사후 SD

            # ── 효과 크기 (calc_effects에서 계산된 값) ───────────────────
            "delta_TG":      o.get("delta_TG", ""),      # 실험군 변화량 (post - pre)
            "delta_CG":      o.get("delta_CG", ""),      # 통제군 변화량
            "SD_pooled_pre": o.get("SD_pooled_pre", ""), # 합동 표준편차 (사전)
            "cohen_d":       o.get("cohen_d", ""),       # Cohen's d 효과 크기
            "hedges_g":      o.get("hedges_g", ""),      # Hedges' g (소표본 보정)

            # ── 분산분석 F값 ──────────────────────────────────────────────
            "F_집단":    o.get("F_group", ""),       # 집단 간(Group) F값
            "F_시간":    o.get("F_time", ""),        # 시간(Time) F값
            "F_집단x시간": o.get("F_interaction", ""), # 집단×시간 상호작용 F값
            "비고":      o.get("note", ""),          # 유의성 표시 및 특이사항
        })

    return pd.DataFrame(rows)  # 행 목록을 pandas DataFrame으로 변환


# ══════════════════════════════════════════════════════════════════════════════
# [J] JSON 추출 유틸리티 함수
# ══════════════════════════════════════════════════════════════════════════════
def extract_json(text: str) -> str:
    """
    AI 응답 텍스트에서 순수 JSON 부분만 추출하는 함수.

    AI가 지시에도 불구하고 가끔 JSON 앞뒤에 설명 텍스트나
    마크다운 코드 블록(```json...```)을 붙이는 경우를 처리.

    처리 순서:
    1. 마크다운 코드 블록 감지: ```json ... ``` 또는 ``` ... ``` 형태
    2. 중괄호 기반 추출: 첫 번째 '{'부터 마지막 '}'까지
    3. 둘 다 실패 시 원본 텍스트 반환 (json.loads가 처리하도록)

    매개변수:
        text (str): AI가 반환한 원본 텍스트

    반환값:
        str: 파싱 가능한 JSON 문자열
    """
    # 패턴 1: 마크다운 코드 블록 안의 내용 추출
    # ```json\n...\n``` 또는 ```\n...\n``` 형태 모두 처리
    m = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text)
    if m:
        return m.group(1).strip()  # 코드 블록 내용만 반환 (앞뒤 공백 제거)

    # 패턴 2: 첫 번째 '{' ~ 마지막 '}' 사이의 내용 추출
    s, e = text.find("{"), text.rfind("}")
    if s != -1 and e != -1:
        return text[s: e + 1]  # '{...}' 범위의 문자열 반환

    return text  # 패턴 매칭 실패 시 원본 그대로 반환


# ══════════════════════════════════════════════════════════════════════════════
# [K] Cohen's d 효과 크기 시각화 함수
# ══════════════════════════════════════════════════════════════════════════════
def make_effect_chart(df: pd.DataFrame, font_name):
    """
    Cohen's d 값을 수평 막대 차트(barh)로 시각화하는 함수.

    차트 구성:
        - 양수(d>0): 파란색 막대 (실험군이 더 향상)
        - 음수(d<0): 빨간색 막대 (통제군이 더 향상)
        - 세로 점선: d=±0.2(소), ±0.5(중), ±0.8(대) 효과 크기 기준선
        - 각 막대 끝에 d 값 텍스트 표시

    매개변수:
        df (pd.DataFrame): 결과 데이터 (cohen_d, outcome_kr 컬럼 필요)
        font_name: matplotlib에 설정된 한국어 폰트 이름 (미사용, 호환성 유지용)

    반환값:
        matplotlib.figure.Figure 또는 None (계산된 d값이 없는 경우)
    """
    # cohen_d 컬럼에서 결측값 제거 후 복사 (원본 보호)
    d_df = df[df["cohen_d"].notna()].copy()

    # 문자열로 저장된 값을 숫자형으로 변환 (변환 불가한 값은 NaN)
    d_df["cohen_d"] = pd.to_numeric(d_df["cohen_d"], errors="coerce")

    # 숫자 변환 실패한 행 제거 후 오름차순 정렬 (차트에서 작은 값이 위에 표시)
    d_df = d_df.dropna(subset=["cohen_d"]).sort_values("cohen_d")

    if d_df.empty:  # 유효한 d값이 없으면 None 반환 (차트 생성 불가)
        return None

    n = len(d_df)  # 결과 변수 개수 (차트 높이 계산에 사용)

    # Figure 크기: 가로 9인치, 세로는 변수 수에 비례 (최소 4인치, 변수당 0.45인치)
    fig, ax = plt.subplots(figsize=(9, max(4, n * 0.45)))

    # d값 부호에 따라 막대 색상 결정 (음수=빨강, 양수=파랑)
    colors = ["#F44336" if v < 0 else "#2196F3" for v in d_df["cohen_d"]]

    # 수평 막대 차트 그리기 (결과 변수명을 y축, d값을 x축)
    bars = ax.barh(d_df["outcome_kr"], d_df["cohen_d"], color=colors, height=0.6)

    # x=0 기준선 (실험군=통제군으로 효과 없음)
    ax.axvline(0, color="black", linewidth=0.8)

    # 효과 크기 기준선 (Cohen, 1988 기준)
    for xv, ls in [(0.2, "--"), (0.5, "-."), (0.8, ":")]:
        for sign in [1, -1]:  # 양수, 음수 방향 모두 표시
            ax.axvline(sign * xv, color="gray", linewidth=0.6, linestyle=ls, alpha=0.5)

    # 각 막대 끝에 d값 텍스트 표시
    for bar, val in zip(bars, d_df["cohen_d"]):
        # 양수면 막대 오른쪽 끝 +0.03, 음수면 왼쪽 끝 -0.03 위치에 텍스트
        xpos = bar.get_width() + 0.03 if val >= 0 else bar.get_width() - 0.03
        ax.text(
            xpos,
            bar.get_y() + bar.get_height() / 2,  # 막대 세로 중앙
            f"{val:.2f}",                          # 소수 2자리 포맷
            va="center",                           # 수직 가운데 정렬
            ha="left" if val >= 0 else "right",    # 방향에 따라 수평 정렬
            fontsize=8
        )

    ax.set_xlabel("Cohen's d", fontsize=10)           # x축 레이블
    ax.set_title("효과 크기 (Cohen's d)", fontsize=11, pad=10)  # 차트 제목
    ax.tick_params(axis="y", labelsize=9)              # y축 글씨 크기
    plt.tight_layout()  # 레이블이 잘리지 않도록 여백 자동 조정
    return fig


# ══════════════════════════════════════════════════════════════════════════════
# [L] 팩트체크 함수
# ══════════════════════════════════════════════════════════════════════════════

def build_factcheck_prompt(extracted_json: str) -> str:
    """
    팩트체크용 AI 프롬프트 생성.
    1차 추출된 JSON 데이터를 포함시켜, 검증 AI가 PDF와 직접 대조하도록 지시.

    매개변수:
        extracted_json (str): 1차 추출 시 AI가 반환한 원본 JSON 문자열

    반환값:
        str: 검증 지시 + 추출 데이터가 포함된 프롬프트 문자열
    """
    return f"""당신은 메타분석 데이터 검증 전문가입니다.
아래 [1차 추출 데이터]가 첨부된 논문 PDF의 실제 수치와 일치하는지 검증해주세요.

[1차 추출 데이터]:
{extracted_json}

PDF를 직접 참조하여 각 수치를 대조한 후, 아래 형식의 **순수 JSON만** 반환하세요 (설명 텍스트 없음).

{{
  "overall_status": "ok" 또는 "has_errors" 또는 "uncertain",
  "summary": "전체 검증 요약 (1~2문장, 한국어)",
  "error_count": 오류 개수(정수),
  "uncertain_count": 불명확 개수(정수),
  "study_check": {{
    "n_TG": {{"status": "ok"|"error"|"uncertain", "original": <원본값>, "verified": <검증값 또는 null>, "note": "근거 위치 (예: Table 1)"}},
    "n_CG": {{"status": "...", "original": ..., "verified": ..., "note": "..."}}
  }},
  "outcomes_check": [
    {{
      "outcome_en": "결과변수 영문명",
      "outcome_kr": "결과변수 한국어명",
      "checks": {{
        "TG_pre_M":   {{"status": "ok"|"error"|"uncertain", "original": <숫자 또는 null>, "verified": <숫자 또는 null>, "note": "근거 위치"}},
        "TG_pre_SD":  {{"status": "...", "original": ..., "verified": ..., "note": "..."}},
        "TG_post_M":  {{"status": "...", "original": ..., "verified": ..., "note": "..."}},
        "TG_post_SD": {{"status": "...", "original": ..., "verified": ..., "note": "..."}},
        "CG_pre_M":   {{"status": "...", "original": ..., "verified": ..., "note": "..."}},
        "CG_pre_SD":  {{"status": "...", "original": ..., "verified": ..., "note": "..."}},
        "CG_post_M":  {{"status": "...", "original": ..., "verified": ..., "note": "..."}},
        "CG_post_SD": {{"status": "...", "original": ..., "verified": ..., "note": "..."}}
      }}
    }}
  ]
}}

검증 기준:
- "ok": PDF의 수치와 정확히 일치
- "error": 불일치 → verified 필드에 PDF의 실제 수치 입력
- "uncertain": PDF에서 명확히 확인 불가 (해당 표 없음, 값 불명확 등)
"""


def factcheck_with_claude(pdf_bytes: bytes, extracted_json: str, api_key: str, model_id: str) -> str:
    """
    Claude로 팩트체크: PDF 원본 + 1차 추출 데이터를 함께 전송하여 교차 검증.

    매개변수:
        pdf_bytes (bytes): PDF 파일 바이너리
        extracted_json (str): 1차 추출 AI의 원본 JSON 응답
        api_key (str): Anthropic API 키
        model_id (str): 검증에 사용할 Claude 모델 ID

    반환값:
        str: 팩트체크 결과 JSON 문자열
    """
    import anthropic
    client = anthropic.Anthropic(api_key=api_key)
    pdf_b64 = base64.standard_b64encode(pdf_bytes).decode("utf-8")  # PDF → base64
    prompt = build_factcheck_prompt(extracted_json)  # 추출 데이터 포함 프롬프트 생성

    resp = client.messages.create(
        model=model_id,
        max_tokens=8192,
        messages=[{
            "role": "user",
            "content": [
                {
                    "type": "document",  # Claude PDF 네이티브 타입
                    "source": {"type": "base64", "media_type": "application/pdf", "data": pdf_b64},
                },
                {"type": "text", "text": prompt},  # 검증 지시 프롬프트
            ],
        }],
    )
    return resp.content[0].text


def factcheck_with_openai(pdf_bytes: bytes, extracted_json: str, api_key: str, model_id: str) -> str:
    """
    OpenAI Vision으로 팩트체크: PDF 이미지 + 1차 추출 데이터를 함께 전송하여 교차 검증.

    매개변수:
        pdf_bytes (bytes): PDF 파일 바이너리
        extracted_json (str): 1차 추출 AI의 원본 JSON 응답
        api_key (str): OpenAI API 키
        model_id (str): 검증에 사용할 GPT 모델 ID

    반환값:
        str: 팩트체크 결과 JSON 문자열
    """
    client = _make_openai_client(api_key)   # httpx 충돌 우회 클라이언트
    images = pdf_to_images_b64(pdf_bytes, dpi=150, max_pages=20)  # PDF → 이미지 변환
    prompt = build_factcheck_prompt(extracted_json)

    # 프롬프트 + 이미지 콘텐츠 구성
    content: list = [{"type": "text", "text": prompt}]
    for img_b64 in images:
        content.append({
            "type": "image_url",
            "image_url": {"url": f"data:image/png;base64,{img_b64}", "detail": "high"},
        })

    resp = client.chat.completions.create(
        model=model_id,
        max_tokens=8192,
        messages=[{"role": "user", "content": content}],
    )
    choice = resp.choices[0]
    if hasattr(choice.message, "refusal") and choice.message.refusal:
        raise ValueError(f"모델 거절: {choice.message.refusal}")
    result = choice.message.content
    if not result:
        raise ValueError(f"빈 응답 (finish_reason={choice.finish_reason})")
    return result


def factcheck_pdf(pdf_bytes: bytes, verify_provider: str, api_key: str,
                  model_id: str, extracted_json: str) -> str:
    """
    팩트체크 디스패처: 검증 제공자에 따라 적절한 함수로 라우팅.

    매개변수:
        pdf_bytes (bytes): PDF 파일 바이너리
        verify_provider (str): 검증에 사용할 API 제공자 이름
        api_key (str): 검증 제공자의 API 키
        model_id (str): 검증에 사용할 모델 ID
        extracted_json (str): 1차 추출 AI의 원본 JSON

    반환값:
        str: 팩트체크 결과 JSON 문자열
    """
    if "Claude" in verify_provider:
        return factcheck_with_claude(pdf_bytes, extracted_json, api_key, model_id)
    else:
        return factcheck_with_openai(pdf_bytes, extracted_json, api_key, model_id)


def parse_factcheck_to_df(fc_data: dict) -> pd.DataFrame:
    """
    팩트체크 결과 딕셔너리를 비교 DataFrame으로 변환.
    각 행: 결과변수명 / 항목 / 원본값 / 검증값 / 상태 / 비고

    매개변수:
        fc_data (dict): AI가 반환한 팩트체크 JSON을 파싱한 딕셔너리

    반환값:
        pd.DataFrame: 비교 결과 표
    """
    # 상태 코드 → 사용자 표시 텍스트 매핑
    STATUS_LABEL = {"ok": "✅ 일치", "error": "❌ 오류", "uncertain": "❓ 불명확"}
    # 검증 대상 수치 필드 목록
    FIELDS = ["TG_pre_M", "TG_pre_SD", "TG_post_M", "TG_post_SD",
              "CG_pre_M", "CG_pre_SD", "CG_post_M", "CG_post_SD"]

    rows = []

    # 연구 기본 정보 검증 결과 (n_TG, n_CG)
    for key, val in fc_data.get("study_check", {}).items():
        rows.append({
            "결과변수":  "연구 정보",
            "항목":      key,
            "원본값":    val.get("original", ""),
            "검증값":    val.get("verified", ""),  # 오류일 때 수정값
            "상태":      STATUS_LABEL.get(val.get("status", ""), val.get("status", "")),
            "근거/비고": val.get("note", ""),
        })

    # 결과 변수별 수치 검증 결과
    for oc in fc_data.get("outcomes_check", []):
        label = f"{oc.get('outcome_kr', '')} ({oc.get('outcome_en', '')})"
        for field in FIELDS:
            chk = oc.get("checks", {}).get(field)
            if chk is None:   # 해당 필드 검증 결과 없으면 건너뜀
                continue
            rows.append({
                "결과변수":  label,
                "항목":      field,
                "원본값":    chk.get("original", ""),
                "검증값":    chk.get("verified", ""),
                "상태":      STATUS_LABEL.get(chk.get("status", ""), chk.get("status", "")),
                "근거/비고": chk.get("note", ""),
            })

    return pd.DataFrame(rows)


def apply_corrections(outcomes: list, fc_data: dict) -> list:
    """
    팩트체크에서 발견된 오류(status="error")를 outcomes 목록에 적용.
    verified 값이 있는 항목만 수정하고, 나머지는 원본 유지.

    매개변수:
        outcomes (list): 현재 결과 변수 딕셔너리 목록
        fc_data (dict): 팩트체크 결과 딕셔너리

    반환값:
        list: 수정이 적용된 outcomes 복사본
    """
    corrected = [dict(o) for o in outcomes]  # 원본 보호를 위한 딥 복사
    NUMERIC_FIELDS = ["TG_pre_M", "TG_pre_SD", "TG_post_M", "TG_post_SD",
                      "CG_pre_M", "CG_pre_SD", "CG_post_M", "CG_post_SD"]

    for oc_check in fc_data.get("outcomes_check", []):
        en = oc_check.get("outcome_en", "")  # 결과 변수 영문명으로 매칭
        for o in corrected:
            if o.get("outcome_en", "") == en:  # 일치하는 결과 변수 찾기
                for field in NUMERIC_FIELDS:
                    chk = oc_check.get("checks", {}).get(field, {})
                    # 오류이고 검증값이 있는 경우에만 수정
                    if chk.get("status") == "error" and chk.get("verified") is not None:
                        o[field] = chk["verified"]
                break  # 해당 변수 찾았으면 다음 oc_check로

    return corrected


# ══════════════════════════════════════════════════════════════════════════════
#  UI 섹션 시작
# ══════════════════════════════════════════════════════════════════════════════

# ── 사이드바 ───────────────────────────────────────────────────────────────────
with st.sidebar:
    st.header("⚙️ 설정")

    # ── API 제공자 선택 (라디오 버튼) ────────────────────────────────────────
    # PROVIDERS 딕셔너리 키 목록을 옵션으로 사용
    provider = st.radio("🏢 API 제공자", list(PROVIDERS.keys()), horizontal=False)
    pconf = PROVIDERS[provider]  # 선택된 제공자의 설정 딕셔너리 저장

    # ── API Key 입력 ────────────────────────────────────────────────────────
    api_key = st.text_input(
        "🔑 API Key",
        type="password",                   # 입력 내용을 마스킹 처리
        placeholder=pconf["key_placeholder"],  # 제공자별 힌트 (sk-ant-... 등)
        help=pconf["key_help"],            # 마우스 오버 시 발급처 안내
    )

    # ── 모델 선택 (드롭다운) ────────────────────────────────────────────────
    # 선택된 제공자의 모델 목록을 드롭다운으로 표시
    model_label = st.selectbox("🤖 모델", list(pconf["models"].keys()))
    model_id = pconf["models"][model_label]  # 표시 이름 → 실제 API 모델 ID 변환

    st.caption(f"📄 PDF 처리: {pconf['pdf_method']}")  # PDF 처리 방식 안내

    # ── API 연결 테스트 버튼 ────────────────────────────────────────────────
    # API Key 입력 시에만 버튼 표시 (api_key가 빈 문자열이면 조건 False)
    if api_key and st.button("🔌 API 연결 테스트", use_container_width=True):
        with st.spinner("연결 확인 중..."):  # 로딩 스피너 표시
            try:
                if "Claude" in provider:
                    import anthropic
                    c = anthropic.Anthropic(api_key=api_key)
                    # 최소 토큰(16)으로 테스트 요청 → 비용 최소화
                    c.messages.create(
                        model=model_id, max_tokens=16,
                        messages=[{"role": "user", "content": "hi"}],
                    )
                else:
                    c = _make_openai_client(api_key)  # httpx 호환 클라이언트 생성
                    c.chat.completions.create(
                        model=model_id, max_tokens=16,
                        messages=[{"role": "user", "content": "hi"}],
                    )
                st.success("✅ 연결 성공!")
            except Exception as _e:
                st.error(f"[오류] {_e}")  # 연결 실패 시 오류 메시지 표시

    st.divider()  # 구분선

    # ── 효과 크기 공식 안내 ─────────────────────────────────────────────────
    st.markdown("### 📐 효과 크기 공식")
    st.markdown("**Cohen's d (Morris, 2008)**")
    st.latex(r"d = \frac{\Delta_{TG} - \Delta_{CG}}{SD_{pooled,pre}}")  # LaTeX 수식
    st.markdown("**Hedges' g (소표본 보정)**")
    st.latex(r"g = d \times \left(1-\frac{3}{4df-1}\right)")

    st.divider()

    # ── Cohen's d 해석 기준표 ───────────────────────────────────────────────
    st.markdown("### 💡 Cohen's d 기준")
    st.markdown(
        "| 값 | 해석 |\n|---|---|\n"
        "| < 0.2 | 효과 없음 |\n| 0.2–0.5 | 소효과 |\n"
        "| 0.5–0.8 | 중간효과 |\n| ≥ 0.8 | 대효과 |"
    )

    # 한국어 폰트 설정 성공 시 사용 중인 폰트 이름 표시
    if KOREAN_FONT:
        st.caption(f"✅ 한국어 폰트: {KOREAN_FONT}")


# ══════════════════════════════════════════════════════════════════════════════
# 메인 화면
# ══════════════════════════════════════════════════════════════════════════════
st.title("📊 메타분석 PDF 코딩 앱")
st.markdown(
    "논문 PDF를 업로드하면 **평균, 표준편차, Cohen's d, Hedges' g, 서브그룹**을 "
    "자동 추출하여 CSV로 저장합니다.  \n"
    "**Anthropic Claude** 또는 **OpenAI ChatGPT** 중 원하는 API를 선택하세요."
)

# ── 현재 선택된 제공자 배지(badge) 표시 ─────────────────────────────────────
# 제공자에 따라 파란색(Claude) 또는 초록색(OpenAI) 배지로 구분
badge_color = "#1565C0" if "Claude" in provider else "#1B5E20"
st.markdown(
    f'<div style="background:{badge_color};color:white;padding:6px 14px;'
    f'border-radius:6px;display:inline-block;font-size:0.9rem;">'
    f'{provider} · {model_label}</div>',
    unsafe_allow_html=True,  # HTML 직접 렌더링 허용
)
st.write("")  # 배지 아래 빈 줄 추가 (간격 확보)

# ── PDF 파일 업로드 ──────────────────────────────────────────────────────────
uploaded = st.file_uploader("📄 논문 PDF 업로드 (최대 32 MB)", type="pdf")

# 파일이 업로드되지 않은 경우: 안내 메시지 + 사용법 표시 후 렌더링 중단
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
    st.stop()  # 이 아래 코드는 실행하지 않음

# ── 파일 크기 검증 ───────────────────────────────────────────────────────────
file_mb = uploaded.size / (1024 * 1024)  # 바이트 → MB 변환
if file_mb > 32:  # 32MB 초과 시 오류 표시 후 중단
    st.error(f"파일 {file_mb:.1f} MB — 32 MB 초과.")
    st.stop()

# 업로드 성공 메시지 (파일명과 크기 표시)
st.success(f"✅ **{uploaded.name}** ({file_mb:.1f} MB)")

# ── API Key 입력 여부 확인 ───────────────────────────────────────────────────
if not api_key:
    st.warning("⬅️ 사이드바에서 API Key를 입력해주세요.")
    st.stop()  # Key 없이는 진행 불가


# ══════════════════════════════════════════════════════════════════════════════
# 분석 제어 버튼
# ══════════════════════════════════════════════════════════════════════════════
# 3개 컬럼으로 분할: [분석 버튼 1/6] [초기화 버튼 1/6] [빈 공간 4/6]
btn_col, reset_col, _ = st.columns([1, 1, 4])
run_btn   = btn_col.button("🔍 분석 시작", type="primary", use_container_width=True)
reset_btn = reset_col.button("🔄 초기화", use_container_width=True)

# ── 초기화 버튼 처리 ─────────────────────────────────────────────────────────
if reset_btn:
    # session_state에서 분석 결과 관련 키 모두 제거
    for k in ["extracted", "study", "outcomes", "raw_json", "used_provider"]:
        st.session_state.pop(k, None)  # 키가 없어도 오류 없이 처리
    st.rerun()  # 페이지 새로고침 (초기 상태로 복귀)

# ── 분석 시작 버튼 처리 ──────────────────────────────────────────────────────
if run_btn:
    # 이전 분석 결과 초기화 (재분석 시 이전 결과가 남지 않도록)
    for k in ["extracted", "study", "outcomes", "raw_json", "used_provider"]:
        st.session_state.pop(k, None)

    pdf_bytes = uploaded.read()              # PDF 파일을 바이트로 읽기
    progress = st.progress(0, text="분석 준비 중...")  # 진행 바 초기화
    status = st.empty()                      # 상태 메시지를 위한 빈 컨테이너

    try:
        # 제공자별 진행 상태 텍스트 업데이트
        if "Claude" in provider:
            progress.progress(15, text="Claude가 PDF를 읽는 중...")
        else:
            progress.progress(10, text="PDF를 이미지로 변환 중...")
            progress.progress(25, text=f"{model_label} Vision에 전송 중...")

        # AI API 호출 (가장 시간이 오래 걸리는 단계)
        raw_text = analyze_pdf(pdf_bytes, provider, api_key, model_id)

        progress.progress(80, text="JSON 파싱 중...")
        json_str = extract_json(raw_text)    # AI 응답에서 JSON 부분만 추출
        data = json.loads(json_str)          # JSON 문자열 → Python 딕셔너리 변환

        # 분석 결과를 session_state에 저장 (페이지 재렌더링 후에도 유지)
        st.session_state.update(
            extracted=True,                  # 분석 완료 플래그
            study=data["study"],             # 연구 기본 정보 딕셔너리
            outcomes=data["outcomes"],       # 결과 변수 목록
            raw_json=raw_text,               # AI 원본 응답 (디버깅용)
            used_provider=provider,          # 사용한 API 제공자 이름
            pdf_bytes=pdf_bytes,             # 팩트체크 시 재사용을 위해 PDF 바이너리 보존
        )
        # 새 분석 시작 시 이전 팩트체크 결과 초기화
        for k in ["factcheck_done", "factcheck_data", "factcheck_raw", "factcheck_provider"]:
            st.session_state.pop(k, None)
        progress.progress(100, text="완료!")
        status.success("✅ 분석 완료!")

    except json.JSONDecodeError as e:
        # JSON 파싱 실패: AI가 잘못된 형식으로 응답한 경우
        progress.empty()
        st.error(f"JSON 파싱 오류: {e}")
        with st.expander("AI 원본 응답"):
            st.code(raw_text, language="json")  # 원본 응답을 보여줘 디버깅 지원
        st.stop()

    except Exception as e:
        # 기타 모든 예외 처리
        progress.empty()
        err_str = str(e)

        # 오류 유형별 안내 메시지 (사용자 친화적 오류 처리)
        if "api_key" in err_str.lower() or "authentication" in err_str.lower() or "401" in err_str:
            st.error("[오류] API Key가 잘못되었거나 권한이 없습니다. Key를 확인해주세요.")
        elif "rate" in err_str.lower() or "429" in err_str:
            st.error("[오류] API 요청 한도 초과. 잠시 후 다시 시도해주세요.")
        elif "model" in err_str.lower() and ("not found" in err_str.lower() or "does not exist" in err_str.lower()):
            st.error(f"[오류] 모델 '{model_id}'을 찾을 수 없습니다. 다른 모델을 선택해주세요.")
        elif "context" in err_str.lower() or "token" in err_str.lower() or "length" in err_str.lower():
            st.error("[오류] PDF가 너무 깁니다. 페이지 수를 줄이거나 다른 모델을 사용해보세요.")
        else:
            st.error(f"[오류] {e}")
            with st.expander("오류 상세 내용"):
                st.exception(e)  # 전체 스택 트레이스 표시 (개발자 디버깅용)
        st.stop()


# ══════════════════════════════════════════════════════════════════════════════
# 분석 결과 표시 (session_state에 결과가 있을 때만 실행)
# ══════════════════════════════════════════════════════════════════════════════
# 분석이 완료되지 않았으면 이 아래 코드를 실행하지 않음
if not st.session_state.get("extracted"):
    st.stop()

# session_state에서 저장된 분석 결과 불러오기
study    = st.session_state["study"]          # 연구 기본 정보
outcomes = st.session_state["outcomes"]       # 결과 변수 목록
used_pv  = st.session_state.get("used_provider", "")  # 사용한 API 제공자

st.divider()

# 사용한 API 표시 (재분석 시 어떤 API를 썼는지 추적용)
st.caption(f"분석에 사용된 API: **{used_pv}**")


# ── 연구 기본 정보 요약 ──────────────────────────────────────────────────────
st.subheader("📋 연구 정보")

# 4개 열로 핵심 정보를 metric 형태로 표시
m1, m2, m3, m4 = st.columns(4)
m1.metric("저자",     study.get("authors", "N/A"))  # 저자명
m2.metric("연도",     study.get("year",    "N/A"))  # 발행연도
m3.metric("훈련군 n", study.get("n_TG",    "N/A"))  # 실험군 표본 수
m4.metric("통제군 n", study.get("n_CG",    "N/A"))  # 통제군 표본 수

# 상세 정보는 접기/펼치기(expander)로 숨겨서 화면 절약
with st.expander("📝 연구 상세 정보"):
    for label, key in [
        ("제목", "title"), ("저널", "journal"),
        ("대상", "population"), ("중재", "intervention"), ("기간", "duration")
    ]:
        v = study.get(key, "")
        if v:  # 값이 있을 때만 표시 (빈 항목 숨김)
            st.markdown(f"**{label}:** {v}")


# ── 표본 크기 확인 및 수정 ───────────────────────────────────────────────────
st.subheader("👥 표본 크기 확인 / 수정")
st.caption("AI가 잘못 읽었을 경우 직접 수정하세요. 수정하면 Cohen's d가 즉시 재계산됩니다.")

nc1, nc2, _ = st.columns([1, 1, 3])  # 입력 필드 2개 + 빈 공간

# number_input: 숫자 직접 입력 위젯
# value: AI 추출값을 기본값으로 (None이거나 1 미만이면 1로 강제)
n_tg = nc1.number_input("훈련군(TG) n", value=max(1, int(study.get("n_TG") or 1)), min_value=1)
n_cg = nc2.number_input("통제군(CG) n", value=max(1, int(study.get("n_CG") or 1)), min_value=1)

# 자유도 및 Hedges' J 실시간 계산 (n 변경 즉시 업데이트)
df_val = n_tg + n_cg - 2           # 자유도
J_val  = 1 - 3 / (4 * df_val - 1) # Hedges' 소표본 보정 계수
st.caption(f"df = {df_val},  Hedges' J = {J_val:.4f}")

# n값을 반영하여 효과 크기 재계산
# dict(o): 원본 리스트 보호를 위해 딕셔너리 복사본 전달
outcomes_calc, _, _ = calc_effects([dict(o) for o in outcomes], n_tg, n_cg)

# 최종 결과 DataFrame 생성 (수정된 n_TG, n_CG 반영)
df_result = to_dataframe({**study, "n_TG": n_tg, "n_CG": n_cg}, outcomes_calc)


# ══════════════════════════════════════════════════════════════════════════════
# 결과 테이블 (행/열 선택 기능 포함)
# ══════════════════════════════════════════════════════════════════════════════
st.divider()
st.subheader(f"📊 추출 결과 — {len(outcomes_calc)}개 변수")

# ── 서브그룹 필터 ────────────────────────────────────────────────────────────
# df_result의 서브그룹 고유값 목록 추출 → "전체" 옵션 추가
subgroups = ["전체"] + sorted(df_result["subgroup_kr"].dropna().unique().tolist())
sel_sg    = st.selectbox("서브그룹 필터", subgroups)  # 드롭다운 선택
# 선택된 서브그룹으로 필터링 (전체면 필터 없음)
disp      = df_result if sel_sg == "전체" else df_result[df_result["subgroup_kr"] == sel_sg]

# ── 기본 표시 컬럼 목록 ──────────────────────────────────────────────────────
# study_id, 저자명 등 메타 정보를 제외한 핵심 분석 컬럼만 기본 표시
_default_cols = [
    "outcome_kr", "subgroup_kr", "단위",
    "TG_pre_M", "TG_pre_SD", "TG_post_M", "TG_post_SD",
    "CG_pre_M", "CG_pre_SD", "CG_post_M", "CG_post_SD",
    "delta_TG", "delta_CG", "cohen_d", "hedges_g", "비고",
]
_all_cols = list(disp.columns)  # DataFrame의 전체 컬럼 목록

# ── 열(Column) 선택 멀티셀렉트 ──────────────────────────────────────────────
# 사용자가 CSV에 포함할 열을 직접 선택. 미선택 시 기본 컬럼 사용
_sel_cols = st.multiselect(
    "📋 열(Column) 선택 — 미선택 시 기본 열 전체 저장",
    options=_all_cols,                 # 선택 가능한 전체 컬럼 목록
    default=[],                        # 기본 선택: 없음 (기본 컬럼 세트 사용)
    placeholder="저장할 열을 선택하세요 (복수 선택 가능)...",
    key=f"col_select_{sel_sg}",        # 서브그룹 변경 시 선택 초기화
)

# 열 선택이 있으면 선택된 열만, 없으면 기본 컬럼 목록 사용
_show_cols = _sel_cols if _sel_cols else [c for c in _default_cols if c in _all_cols]

st.caption("💡 **행 클릭** → 행 선택(복수 가능) · 선택한 행+열 데이터만 CSV로 저장 · 미선택 시 전체 저장")

# ── 인터랙티브 결과 테이블 ───────────────────────────────────────────────────
# on_select="rerun": 행 선택 시 페이지 자동 재렌더링 → 선택 결과 즉시 반영
# selection_mode="multi-row": 여러 행을 동시에 선택 가능
event = st.dataframe(
    disp[_show_cols],             # 표시할 데이터 (필터링 + 컬럼 적용)
    use_container_width=True,     # 화면 전체 너비 사용
    height=420,                   # 테이블 높이 고정 (420px)
    on_select="rerun",            # 선택 이벤트 발생 시 앱 재실행
    selection_mode="multi-row",   # 다중 행 선택 모드
    key=f"result_table_{sel_sg}_{str(_sel_cols)}",  # 필터 변경 시 상태 초기화
)

# 선택된 행 인덱스 목록 (아무것도 선택 안 하면 빈 리스트)
_sel_rows = event.selection.rows   # list[int]: 선택된 행의 위치 인덱스

# ── 내보낼 데이터(export_df) 결정 ────────────────────────────────────────────
export_df = disp[_show_cols].copy()  # 현재 표시 데이터 복사

if _sel_rows:  # 특정 행이 선택된 경우
    export_df = export_df.iloc[_sel_rows]  # iloc: 위치 기반 행 슬라이싱

# CSV 저장 예정 정보 표시
n_ok = df_result["cohen_d"].notna().sum()                    # 유효한 Cohen's d 개수
_row_info = f"{len(export_df)}행" if _sel_rows else f"전체 {len(disp)}행"
_col_info = f"{len(_show_cols)}열 (선택)" if _sel_cols else f"{len(_show_cols)}열 (기본)"
st.caption(f"Cohen's d 계산됨: {n_ok}/{len(df_result)}개  ·  CSV 저장 예정: **{_row_info} × {_col_info}**")


# ══════════════════════════════════════════════════════════════════════════════
# Cohen's d 효과 크기 차트
# ══════════════════════════════════════════════════════════════════════════════
st.divider()
st.subheader("📈 Cohen's d 효과 크기 분포")

fig = make_effect_chart(df_result, KOREAN_FONT)  # 전체 결과 기준 차트 생성
if fig:
    st.pyplot(fig, use_container_width=True)  # 차트를 Streamlit에 렌더링
    plt.close(fig)  # 메모리 해제 (matplotlib Figure는 수동 닫기 필요)
else:
    st.info("계산 가능한 Cohen's d가 없습니다.")


# ══════════════════════════════════════════════════════════════════════════════
# CSV 다운로드
# ══════════════════════════════════════════════════════════════════════════════
st.divider()

# export_df를 CSV 바이트로 변환
# encoding="utf-8-sig": Excel에서 한국어가 깨지지 않는 UTF-8 BOM 형식
csv_bytes = export_df.to_csv(index=False, encoding="utf-8-sig").encode("utf-8-sig")

# 다운로드 파일명 생성: PDF 파일명 기반, 특수문자 제거, .pdf → _meta_coding.csv
out_fname = re.sub(r"[^\w가-힣.\- ]", "_", uploaded.name).replace(".pdf", "_meta_coding.csv")

dl1, _ = st.columns([1, 4])  # 버튼 너비 제한 (전체 너비의 1/5)
dl1.download_button(
    "⬇️ CSV 다운로드",
    data=csv_bytes,          # 다운로드할 데이터 (바이트)
    file_name=out_fname,     # 저장될 파일명
    mime="text/csv",         # MIME 타입
    type="primary",          # 파란색 강조 버튼
    use_container_width=True,
)


# ══════════════════════════════════════════════════════════════════════════════
# AI 원본 응답 확인 (디버깅/검증용)
# ══════════════════════════════════════════════════════════════════════════════
with st.expander("🔧 AI 원본 JSON 응답 보기"):
    # AI가 반환한 원본 텍스트를 JSON 형식으로 하이라이팅하여 표시
    st.code(st.session_state.get("raw_json", ""), language="json")


# ══════════════════════════════════════════════════════════════════════════════
# 팩트체크 — 교차 검증
# ══════════════════════════════════════════════════════════════════════════════
st.divider()
st.subheader("🔍 팩트체크 — 교차 검증")
st.markdown(
    "1차 추출에 사용한 AI와 **다른 AI**가 동일한 PDF를 다시 읽어 수치의 정확성을 교차 검증합니다.  \n"
    "불일치 항목이 발견되면 수정값을 확인하고 **수정사항 적용** 버튼으로 Cohen's d를 재계산할 수 있습니다."
)

# ── 검증 제공자 결정 (추출한 제공자의 반대) ─────────────────────────────────
# used_pv: 1차 추출 시 사용한 API 제공자 이름
if "Claude" in used_pv:
    verify_provider_name = "🟢 OpenAI ChatGPT"   # Claude로 추출 → OpenAI로 검증
else:
    verify_provider_name = "🔵 Anthropic Claude"  # OpenAI로 추출 → Claude로 검증

vconf = PROVIDERS[verify_provider_name]  # 검증 제공자 설정 딕셔너리

# 추출↔검증 제공자 흐름 표시
fc_badge = (
    f'<div style="background:#37474F;color:white;padding:8px 16px;border-radius:6px;'
    f'display:inline-block;font-size:0.9rem;">'
    f'추출&nbsp;&nbsp;<b>{used_pv}</b>&nbsp;&nbsp;→&nbsp;&nbsp;검증&nbsp;&nbsp;<b>{verify_provider_name}</b></div>'
)
st.markdown(fc_badge, unsafe_allow_html=True)
st.write("")

# ── 검증 모델 & API Key 입력 ─────────────────────────────────────────────────
fc_c1, fc_c2 = st.columns(2)

with fc_c1:
    # 검증 제공자의 모델 목록을 드롭다운으로 표시
    verify_model_label = st.selectbox(
        "검증 모델 선택",
        list(vconf["models"].keys()),
        key="verify_model",
    )
    verify_model_id = vconf["models"][verify_model_label]  # 표시명 → 실제 모델 ID

with fc_c2:
    # 검증 제공자의 API 키 입력 (1차 추출 키와 별도)
    verify_api_key = st.text_input(
        f"{verify_provider_name} API Key",
        type="password",
        placeholder=vconf["key_placeholder"],
        help=vconf["key_help"],
        key="verify_api_key",
    )

# ── 팩트체크 실행 버튼 ───────────────────────────────────────────────────────
fc_btn_col, _ = st.columns([1, 3])
fc_btn = fc_btn_col.button(
    "🔍 팩트체크 시작",
    type="primary",
    use_container_width=True,
    disabled=not verify_api_key,  # API Key 없으면 비활성화
    key="factcheck_btn",
)

if fc_btn and verify_api_key:
    _pdf = st.session_state.get("pdf_bytes")  # 저장된 PDF 바이너리 재사용
    if not _pdf:
        st.error("[오류] PDF 데이터를 찾을 수 없습니다. 분석을 다시 실행해주세요.")
    else:
        with st.spinner(f"{verify_provider_name}가 PDF를 재검토하는 중... (30초~2분 소요)"):
            try:
                # 팩트체크 API 호출: PDF + 1차 추출 JSON을 함께 전송
                fc_raw = factcheck_pdf(
                    _pdf,
                    verify_provider_name,
                    verify_api_key,
                    verify_model_id,
                    st.session_state.get("raw_json", ""),  # 1차 추출 원본 JSON
                )
                # 결과 파싱
                fc_json_str = extract_json(fc_raw)
                fc_data = json.loads(fc_json_str)

                # 팩트체크 결과를 session_state에 저장
                st.session_state.update(
                    factcheck_done=True,
                    factcheck_data=fc_data,
                    factcheck_raw=fc_raw,
                    factcheck_provider=verify_provider_name,
                )
                st.rerun()  # 결과 표시를 위해 페이지 재렌더링

            except json.JSONDecodeError as _e:
                st.error(f"[오류] 팩트체크 JSON 파싱 실패: {_e}")
                with st.expander("검증 AI 원본 응답"):
                    st.code(fc_raw, language="json")
            except Exception as _e:
                st.error(f"[오류] 팩트체크 실패: {_e}")
                with st.expander("오류 상세"):
                    st.exception(_e)

# ── 팩트체크 결과 표시 ────────────────────────────────────────────────────────
if st.session_state.get("factcheck_done"):
    fc_data      = st.session_state["factcheck_data"]
    fc_pv        = st.session_state.get("factcheck_provider", "")
    overall      = fc_data.get("overall_status", "")
    summary      = fc_data.get("summary", "")
    error_count  = fc_data.get("error_count", 0)
    uncertain_count = fc_data.get("uncertain_count", 0)

    # 전체 상태 배지
    STATUS_COLOR = {"ok": "#2E7D32", "has_errors": "#C62828", "uncertain": "#E65100"}
    STATUS_TEXT  = {"ok": "✅ 이상 없음", "has_errors": "❌ 오류 발견", "uncertain": "❓ 불명확 항목 있음"}
    badge_bg = STATUS_COLOR.get(overall, "#37474F")
    badge_txt = STATUS_TEXT.get(overall, overall)

    st.markdown(
        f'<div style="background:{badge_bg};color:white;padding:8px 16px;border-radius:6px;'
        f'display:inline-block;font-size:0.95rem;font-weight:bold;">{badge_txt}</div>',
        unsafe_allow_html=True,
    )
    st.write("")

    # 요약 문장 및 통계
    if summary:
        st.info(f"**검증 요약:** {summary}")

    # 오류/불명확 개수 표시
    cnt_c1, cnt_c2, cnt_c3 = st.columns(3)
    cnt_c1.metric("검증 제공자", fc_pv.split()[1] if " " in fc_pv else fc_pv)
    cnt_c2.metric("오류 항목", f"{error_count}개", delta=None)
    cnt_c3.metric("불명확 항목", f"{uncertain_count}개", delta=None)

    # ── 상세 비교 테이블 ──────────────────────────────────────────────────────
    st.markdown("#### 항목별 상세 검증 결과")
    fc_df = parse_factcheck_to_df(fc_data)  # 비교 DataFrame 생성

    if not fc_df.empty:
        # 상태 열 기준으로 색상 하이라이트
        def _highlight_status(row):
            """상태에 따라 행 배경색 결정"""
            s = row.get("상태", "")
            if "오류" in s:
                return ["background-color: #FFEBEE"] * len(row)   # 연빨강
            elif "불명확" in s:
                return ["background-color: #FFF3E0"] * len(row)   # 연주황
            elif "일치" in s:
                return ["background-color: #E8F5E9"] * len(row)   # 연초록
            return [""] * len(row)

        st.dataframe(
            fc_df.style.apply(_highlight_status, axis=1),
            use_container_width=True,
            height=min(600, 45 + len(fc_df) * 36),  # 행 수에 비례한 높이
        )

        # 오류 항목만 별도 표시
        error_rows = fc_df[fc_df["상태"].str.contains("오류", na=False)]
        if not error_rows.empty:
            st.markdown(f"#### ⚠️ 오류 발견 항목 ({len(error_rows)}개)")
            st.dataframe(
                error_rows[["결과변수", "항목", "원본값", "검증값", "근거/비고"]],
                use_container_width=True,
                hide_index=True,
            )

            # ── 수정사항 적용 버튼 ────────────────────────────────────────────
            st.warning(
                f"위 {len(error_rows)}개 항목에서 원본값과 다른 수치가 발견되었습니다.  \n"
                "'**수정사항 적용**'을 클릭하면 검증값으로 데이터가 업데이트되고 Cohen's d가 재계산됩니다."
            )
            apply_col, _ = st.columns([1, 3])
            if apply_col.button("✏️ 수정사항 적용 후 재계산", type="primary", use_container_width=True):
                # 오류 항목에 검증값 적용
                corrected_outcomes = apply_corrections(
                    st.session_state["outcomes"], fc_data
                )
                st.session_state["outcomes"] = corrected_outcomes  # 수정된 outcomes 저장
                # 팩트체크 결과 초기화 (수정 적용 후 재검증 유도)
                for k in ["factcheck_done", "factcheck_data", "factcheck_raw", "factcheck_provider"]:
                    st.session_state.pop(k, None)
                st.success("수정사항이 적용되었습니다. Cohen's d가 재계산됩니다.")
                st.rerun()
        else:
            st.success("모든 수치가 PDF 원문과 일치합니다.")

    # 검증 AI 원본 응답 확인
    with st.expander("🔧 검증 AI 원본 JSON 응답 보기"):
        st.code(st.session_state.get("factcheck_raw", ""), language="json")
