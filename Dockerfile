# 1. 파이썬 3.11 슬림 버전 사용 (가볍고 빠름)
FROM python:3.11-slim

# 2. 필수 시스템 패키지 설치 (타임존 및 빌드 도구)
RUN apt-get update && apt-get install -y \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

# 3. 작업 디렉토리 설정
WORKDIR /app

# 4. 종속성 파일 복사 및 설치
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 5. 소스 코드 복사
COPY . .

# 6. Cloud Run 포트 설정 (8080)
ENV PORT 8080

# 7. 서버 실행 명령 (uvicorn 사용)
# main.py의 app 객체를 실행합니다.
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]
