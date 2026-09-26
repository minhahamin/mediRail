# MediRail API (FastAPI + MCP 서버). 빌드 컨텍스트는 저장소 루트다: docker build -f backend/Dockerfile .
# MCP 서버(mcp_servers/)와 스킬(skills/)은 백엔드가 서브프로세스(stdio)로 띄우므로 같은 이미지에 넣는다.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    MEDIRAIL_ENV=production \
    MEDIRAIL_DUR_CACHE=/tmp/dur_cache.db

WORKDIR /app
COPY backend/requirements.txt backend/requirements.txt
RUN pip install -r backend/requirements.txt

COPY backend/app backend/app
COPY mcp_servers mcp_servers
COPY skills skills

# 비루트 사용자로 실행
RUN useradd --create-home --uid 10001 medirail && chown -R medirail /app
USER medirail

WORKDIR /app/backend
# Railway는 PORT를 주입한다
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers --forwarded-allow-ips='*'"]
