@echo off
chcp 65001 > nul
echo ============================================
echo  메타분석 PDF 코딩 앱 시작
echo ============================================

call conda activate py310_2

echo [1/2] 필수 패키지 확인/설치 중...
pip install "anthropic>=0.40.0" "openai>=1.0.0" "pymupdf>=1.23.0" -q

set PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION=python
set PYTHONIOENCODING=utf-8

echo [2/2] Streamlit 앱 시작 (포트 8503)...
echo.
echo 브라우저에서 http://localhost:8503 을 열어주세요.
echo 종료: Ctrl+C
echo.

streamlit run app.py --server.port 8503
pause
