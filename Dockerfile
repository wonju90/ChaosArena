# 가볍고 안정적인 파이썬 3.11 slim 이미지를 기반으로 사용
FROM python:3.11-slim

WORKDIR /app

# 의존성 파일만 먼저 복사해서 설치 (소스 코드만 바뀌었을 때 pip install을 다시 안 하도록
# Docker 레이어 캐시를 활용하기 위함)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 나머지 앱 소스 복사
COPY . .

EXPOSE 5000

# 컨테이너 안에서는 클러스터 모드로 동작해야 하므로 LOCAL_MODE=false를 기본값으로 둔다.
# (K8s Deployment YAML에서 이 값을 다시 지정하면 그 값이 우선 적용됨)
ENV LOCAL_MODE=false

# app.py가 records / current_mission 같은 게임 상태를 파이썬 메모리 변수로 저장하기 때문에,
# 프로세스를 여러 개 띄우면(예: gunicorn --workers 2) 각 프로세스가 서로 다른 메모리를 가져서
# 상태가 꼬인다. 그래서 단일 프로세스로 뜨는 Flask 내장 서버(app.py의 app.run)를 그대로 쓴다.
# threaded=True(app.py 참고)로 되어 있어서 이 데모 규모에서는 동시 요청도 문제없이 처리된다.
CMD ["python", "app.py"]
