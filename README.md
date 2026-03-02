# 📊 메타분석 PDF 코딩 앱 (Meta-Analysis PDF Coding App)

논문 PDF를 업로드하면 AI가 자동으로 통계 데이터를 추출하고
**Cohen's d · Hedges' g** 효과 크기를 계산하여 CSV로 저장하는 Streamlit 웹앱입니다.

---

## 주요 기능

| 기능 | 설명 |
|------|------|
| PDF 자동 파싱 | AI가 논문의 모든 결과 테이블에서 Mean, SD, F값을 추출 |
| 효과 크기 자동 계산 | Cohen's d (Morris, 2008) 및 Hedges' g 소표본 보정 |
| 이중 API 지원 | Anthropic Claude / OpenAI ChatGPT 선택 사용 |
| 인터랙티브 표 | 행 클릭으로 원하는 데이터 선택, 열 선택 멀티셀렉트 |
| CSV 다운로드 | 선택한 행·열만 또는 전체 결과를 Excel 호환 UTF-8 BOM CSV로 저장 |
| API 연결 테스트 | 분석 전 API Key·모델 유효성 사전 확인 버튼 |

---

## 통계 데이터 추출 과정

### 전체 파이프라인

```
논문 PDF
   │
   ▼
[Claude]  PDF 원본 base64 인코딩 → document 타입으로 직접 전송
[ChatGPT] pymupdf로 페이지별 PNG 변환(150dpi) → image_url Vision 전송
   │
   ▼
AI 모델 (Claude / GPT-4o 등)
   - 논문 전체를 읽고 결과 섹션·테이블 식별
   - 실험군(TG)과 통제군(CG) 자동 구분
   - 사전(pre)·사후(post) 평균과 SD 추출
   - F값, 유의성 표시 추출
   - 순수 JSON 형식으로 반환
   │
   ▼
JSON 파싱 (extract_json → json.loads)
   - 마크다운 코드블록 제거
   - { } 범위 추출
   │
   ▼
효과 크기 계산 (calc_effects)
   - Cohen's d, Hedges' g 자동 계산
   │
   ▼
pandas DataFrame → CSV 다운로드
```

---

### Step 1 — PDF 전송 방식

#### Anthropic Claude (권장)
Claude API는 **PDF 네이티브 지원** 기능을 제공합니다.
PDF 파일 전체를 base64로 인코딩하여 `document` 타입 콘텐츠로 전송하므로
텍스트·표·수식의 레이아웃이 그대로 보존됩니다.

```python
# Claude API 전송 구조
{
  "type": "document",
  "source": {
    "type": "base64",
    "media_type": "application/pdf",
    "data": "<base64 인코딩된 PDF>"
  }
}
```

#### OpenAI ChatGPT
OpenAI API는 PDF를 직접 지원하지 않으므로
`pymupdf` 라이브러리로 **페이지별 PNG 이미지**로 변환 후 Vision API로 전송합니다.

```
PDF → [pymupdf 렌더링 150dpi] → 페이지1.png, 페이지2.png, ...
     → base64 인코딩 → image_url (detail: "high") 로 전송
```

| 설정값 | 의미 |
|--------|------|
| `dpi=150` | 논문 표·수식이 선명하게 보이는 해상도 |
| `max_pages=20` | 토큰 한도 초과 방지 (페이지당 ~765 토큰) |
| `detail="high"` | 고해상도 분석 모드 (표 내 숫자 정확도 향상) |

---

### Step 2 — AI 프롬프트와 추출 규칙

AI에게 전달되는 지시문(프롬프트)은 다음 6가지 규칙을 포함합니다.

| 규칙 | 내용 |
|------|------|
| **① 전체 테이블 추출** | 논문의 모든 결과 테이블에서 Pre/Post 평균(M)과 SD를 추출 |
| **② ± 기호 처리** | `45.0±6.08` → `M=45.0, SD=6.08` 으로 분리 |
| **③ 군 구분** | 훈련군·실험군·EG·TG → 실험군(TG) / 통제군·대조군·CG → 통제군(CG) |
| **④ F값 처리** | `*`, `**` 표시는 note 필드에 포함 (예: `F=9.65, p<0.01`) |
| **⑤ 결측값 처리** | 측정값 없으면 `null` (계산 불가 시 Cohen's d도 null) |
| **⑥ 서브그룹 분류** | 논문 결과 섹션 제목 기준 (신체구성, 건강관련체력, 심리적 변인 등) |

---

### Step 3 — AI가 반환하는 JSON 구조

AI는 아래 형식의 **순수 JSON**을 반환합니다 (설명 텍스트 없음).

```json
{
  "study": {
    "authors": "Song et al.",
    "year": "2013",
    "journal": "Journal of Exercise Science",
    "title": "Effects of exercise on body composition...",
    "n_TG": 15,
    "n_CG": 15,
    "population": "비만 중년 여성",
    "intervention": "12주 복합운동 프로그램",
    "duration": "12주, 주 3회, 60분/회"
  },
  "outcomes": [
    {
      "outcome_kr": "체중",
      "outcome_en": "Body weight",
      "unit": "kg",
      "subgroup_kr": "신체구성",
      "subgroup_en": "Body composition",
      "TG_pre_M": 72.3,
      "TG_pre_SD": 8.1,
      "TG_post_M": 68.5,
      "TG_post_SD": 7.9,
      "CG_pre_M": 71.8,
      "CG_pre_SD": 7.6,
      "CG_post_M": 72.1,
      "CG_post_SD": 7.8,
      "F_group": null,
      "F_time": 12.45,
      "F_interaction": 9.65,
      "note": "Time p<0.01; G×T p<0.05"
    }
  ]
}
```

---

### Step 4 — Cohen's d 계산 과정 (단계별 예시)

위 체중 데이터를 예로 들면:

**① 변화량(Δ) 계산**
```
Δ_TG = 68.5 - 72.3 = -3.8 kg   (실험군: 3.8kg 감소)
Δ_CG = 72.1 - 71.8 = +0.3 kg   (통제군: 0.3kg 증가)
```

**② 사전 측정 합동 표준편차 계산 (n_TG=15, n_CG=15)**
```
df = 15 + 15 - 2 = 28

SD_pooled = sqrt(((15-1)×8.1² + (15-1)×7.6²) / 28)
          = sqrt((14×65.61 + 14×57.76) / 28)
          = sqrt((918.54 + 808.64) / 28)
          = sqrt(61.72)
          = 7.86
```

**③ Cohen's d 계산**
```
d = (Δ_TG - Δ_CG) / SD_pooled
  = (-3.8 - 0.3) / 7.86
  = -4.1 / 7.86
  = -0.52   → 중간 효과 크기
```

**④ Hedges' g 소표본 보정**
```
J = 1 - 3 / (4×28 - 1) = 1 - 3/111 = 0.973

g = -0.52 × 0.973 = -0.51
```

> **부호 해석**: d < 0이면 실험군이 더 감소(또는 통제군이 더 증가),
> 체중 감소가 목표인 경우 음수 d가 중재 효과를 의미합니다.

---

### Step 5 — JSON 파싱 안전 처리

AI가 JSON 외 텍스트를 포함하는 경우를 자동으로 처리합니다.

| 케이스 | 처리 방법 |
|--------|----------|
| ` ```json ... ``` ` 마크다운 블록 | 정규식으로 내용만 추출 |
| 앞뒤 설명 텍스트 포함 | `{` ~ `}` 범위만 잘라냄 |
| 순수 JSON | 그대로 파싱 |

---

## 효과 크기 계산 공식

**Cohen's d (Morris, 2008)**

$$d = \frac{\Delta_{TG} - \Delta_{CG}}{SD_{pooled,pre}}$$

- $\Delta$ = 사후(post) 평균 − 사전(pre) 평균
- $SD_{pooled,pre} = \sqrt{\frac{(n_{TG}-1)SD_{TG,pre}^2 + (n_{CG}-1)SD_{CG,pre}^2}{n_{TG}+n_{CG}-2}}$

**Hedges' g (소표본 보정)**

$$g = d \times \left(1 - \frac{3}{4df - 1}\right)$$

**해석 기준 (Cohen, 1988)**

| Cohen's d | 해석 |
|-----------|------|
| < 0.2 | 효과 없음 |
| 0.2 – 0.5 | 소효과 (small) |
| 0.5 – 0.8 | 중간효과 (medium) |
| ≥ 0.8 | 대효과 (large) |

---

## 설치 및 실행

### 요구 환경

- Python 3.10+
- conda 또는 pip

### 빠른 실행 (Windows)

```bash
# run.bat 더블클릭 또는 터미널에서 실행
run.bat
```

`run.bat`이 자동으로 수행하는 작업:
1. `conda activate py310_2` 환경 활성화
2. 필수 패키지 설치 (`anthropic`, `openai`, `pymupdf`)
3. `PYTHONIOENCODING=utf-8` 설정 (한국어 인코딩 오류 방지)
4. Streamlit 앱 포트 8503에서 실행

### 수동 실행

```bash
# 패키지 설치
pip install streamlit anthropic openai pymupdf matplotlib pandas

# 앱 실행
set PYTHONIOENCODING=utf-8
streamlit run app.py --server.port 8503
```

브라우저에서 `http://localhost:8503` 접속

---

## 사용 방법

```
1. 사이드바에서 API 제공자(Claude / ChatGPT) 선택
2. API Key 입력 → "API 연결 테스트" 버튼으로 확인
3. 논문 PDF 업로드 (최대 32MB)
4. "분석 시작" 클릭 → AI가 자동 추출
5. 표본 크기(n) 확인·수정 → Cohen's d 즉시 재계산
6. 결과 표에서 원하는 행 클릭 or 열 선택
7. "CSV 다운로드"
```

---

## API 제공자별 PDF 처리 방식

| 제공자 | 처리 방식 | 특징 |
|--------|----------|------|
| **Anthropic Claude** | PDF 원본 직접 전송 | 가장 정확, 레이아웃 보존 |
| **OpenAI ChatGPT** | PDF → 페이지 이미지 → Vision API | 최대 20페이지, 150dpi |

---

## 지원 모델

### Anthropic Claude
| 모델 | 용도 |
|------|------|
| Claude Sonnet 4.6 (권장) | 속도·정확도 균형 |
| Claude Opus 4.6 (고정확도) | 최고 정확도, 복잡한 논문 |
| Claude Haiku 4.5 (빠름) | 빠른 처리, 간단한 논문 |

### OpenAI ChatGPT
| 모델 | 용도 |
|------|------|
| GPT-4.1 (최신·최고성능) | 2025년 최신 모델 |
| GPT-4o (권장) | Vision 지원, 균형 |
| GPT-4o mini (저비용) | 저렴하고 빠름 |
| GPT-4 Turbo | 이전 세대 고성능 |

---

## 출력 CSV 컬럼 설명

| 컬럼 | 설명 |
|------|------|
| `study_id` | 제1저자성+연도 (예: Song2013) |
| `저자` | 전체 저자명 |
| `발행연도` | 4자리 연도 |
| `저널` | 저널명 |
| `대상` | 연구 대상 설명 |
| `outcome_kr` | 결과 변수명 (한국어) |
| `outcome_en` | 결과 변수명 (영어) |
| `단위` | 측정 단위 (kg, %, cm 등) |
| `subgroup_kr` | 서브그룹 카테고리 (한국어) |
| `subgroup_en` | 서브그룹 카테고리 (영어) |
| `n_TG` / `n_CG` | 실험군 / 통제군 표본 크기 |
| `TG_pre_M` / `TG_pre_SD` | 실험군 사전 평균 / SD |
| `TG_post_M` / `TG_post_SD` | 실험군 사후 평균 / SD |
| `CG_pre_M` / `CG_pre_SD` | 통제군 사전 평균 / SD |
| `CG_post_M` / `CG_post_SD` | 통제군 사후 평균 / SD |
| `delta_TG` / `delta_CG` | 실험군 / 통제군 변화량 (post−pre) |
| `SD_pooled_pre` | 사전 측정 합동 표준편차 |
| `cohen_d` | Cohen's d 효과 크기 |
| `hedges_g` | Hedges' g (소표본 보정) |
| `F_집단` | 집단 간 F값 |
| `F_시간` | 시간 F값 |
| `F_집단x시간` | 집단×시간 상호작용 F값 |
| `비고` | 유의성 표시 및 특이사항 |

---

## 알려진 문제 및 해결책

### httpx proxies 오류
```
Client.__init__() got an unexpected keyword argument 'proxies'
```
**원인**: httpx 0.28+ 에서 `proxies` 파라미터 제거
**해결**: `_make_openai_client()` 함수에서 `httpx.Client()`를 직접 생성하여 전달

### Windows 인코딩 오류
```
'ascii' codec can't encode character
```
**원인**: Windows 콘솔 기본 인코딩이 ASCII
**해결**: 앱 시작 시 `sys.stdout.reconfigure(encoding="utf-8")` 적용
또는 `set PYTHONIOENCODING=utf-8` 환경 변수 설정

---

## 참고 문헌

- Cohen, J. (1988). *Statistical power analysis for the behavioral sciences* (2nd ed.).
- Morris, S. B. (2008). Estimating effect sizes from pretest-posttest-control group designs. *Organizational Research Methods, 11*(2), 364–386.
- Hedges, L. V., & Olkin, I. (1985). *Statistical methods for meta-analysis*.

---

## 라이선스

MIT License
