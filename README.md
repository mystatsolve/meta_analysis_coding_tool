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
