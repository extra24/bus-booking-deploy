# 🚌 명절 버스 예매 시스템 (대규모 트래픽 처리)

## 개요

- 명절 기간에 급증하는 대규모 트래픽을 SQS 기반의 비동기 아키텍처로 안정적으로 처리하는 흐름을 연습한다.
- AWS의 서버리스 서비스(S3, API Gateway, Lambda, DynamoDB, SQS)를 활용해 실제 배포 가능한 구조를 구현한다.
- 주요 학습 목표는 백엔드 분산 처리에 있으므로, 프론트엔드 및 배포는 최소한의 기능으로 구현한다.

## 배포 과정

### 0. 리전

- 리전 선택 : `ap-northeast-2 (서울)`

### 1. S3

#### 1) S3 콘솔 -> 버킷 만들기

- 갯수 : 1개 (웹 호스팅 + 통계 파일 저장)
- 버킷 명 : `aram-app-bucket`
- 퍼블릭 액세스 차단 : **해제** (웹 공개 필요)
- 버전관리 / 기본 암호화 : 기본값 그대로

#### 2) 정적 웹 사이트 호스팅 활성화

- 버킷 -> **속성(Properties)** -> 정적 웹 사이트 호스팅 -> 활성화
- 인덱스 문서 : `index.html`
- 화면 하단에 웹사이트 엔드포인트(URL) 표시됨(HTTP)

> S3 정적 웹 엔드포인트는 HTTP만 지원하지만 내부에서 HTTPS 객체 URL 을 가져오는 건 CORS만 설정해주면 문제 없다.

#### 3) 버킷 정책(공개 읽기)

- 버킷 -> **권한(Permissions)** -> 버킷 정책 편집

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "PublicReadWebsite",
      "Effect": "Allow",
      "Principal": "*",
      "Action": "s3:GetObject",
      "Resource": "arn:aws:s3:::aram-app-bucket/*"
    }
  ]
}
```

#### 4) CORS 설정

- 버킷 -> **권한(Permissions)** -> **CORS 구성**

```xml
<CORSConfiguration>
  <CORSRule>
    <AllowedOrigin>*</AllowedOrigin>
    <AllowedMethod>GET</AllowedMethod>
    <AllowedHeader>*</AllowedHeader>
    <ExposeHeader>ETag</ExposeHeader>
  </CORSRule>
</CORSConfiguration>
```

#### 5) 파일 업로드

- `index.html` 업로드 (콘텐츠 유형: text/html)
- `stats.json` (초기 파일) 업로드: 내용 {"requests":0,"processed":0,"success":0} (콘텐츠 유형: application/json)
- 이후 `stats.json`은 `consumer Lambda`가 계속 덮어씀

### 2. DynamoDB

#### 1) DynamoDB 콘솔 -> 테이블 생성

- 이름 : `aram-stats`
- 파티션 키 : `id` (문자열)
- 용량 모드: **온디맨드(PAY_PER_REQUEST)**

#### 2) 초기 아이템 추가

```
id = "total"
requests = 0(Number), processed = 0(Number), success = 0(Number)
```

### 3. SQS

#### 1) SQS 콘솔 -> 큐 생성

> 큐 ARN/URL은 나중에 Lambda 환경변수/권한에서 필요함.

- 유형 : **표준(Standard)**
- 이름 : `aram-queue`
- 가시성 타임아웃: **60초** (consumer 처리시간에 맞춰 조정)

### 4. Lambda 역할(IAM)

> 역할은 Lambda 함수 만들고 나서 교체해줘도 됨

#### 1) `Producer` 실행 역할

- IAM -> 역할 생성 -> 신뢰할 주체 : Lambda
- DynamoDB 권한 추가

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": ["dynamodb:GetItem", "dynamodb:UpdateItem"],
      "Resource": "arn:aws:dynamodb:ap-northeast-2:<계정ID>:table/aram-stats"
    }
  ]
}
```

- SQS 보내기 권한

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": ["sqs:GetQueueUrl", "sqs:SendMessage"],
      "Resource": "arn:aws:sqs:ap-northeast-2:<계정ID>:aram-queue"
    }
  ]
}
```

#### 2) `Consumer` 실행 역할

- IAM → 역할 생성 → 신뢰할 주체: Lambda
- DynamoDB 권한 추가 (`Producer` 와 동일)

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": ["dynamodb:GetItem", "dynamodb:UpdateItem"],
      "Resource": "arn:aws:dynamodb:ap-northeast-2:<계정ID>:table/aram-stats"
    }
  ]
}
```

- S3 PutObject

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": ["s3:PutObject"],
      "Resource": "arn:aws:s3:::aram-app-bucket/stats.json"
    }
  ]
}
```

### 5. Lambda 함수 생성 & 코드 업로드

#### 1) `Producer` 생성 (HTTP 엔드포인트)

- 이름 : `aram-producer`
- 런타임 : Python 3.12
- Architecture: arm64(비용↓) 또는 x86_64
- Execution role: 위의 producer 역할 선택
- 코드 업로드 : `producer.py` 내용 넣기
- 핸들러 : `lambda_function.lambda_handler` 로 설정
- 환경 변수

```
REGION=ap-northeast-2
STATS_TABLE=aram-stats
QUEUE_NAME=aram-queue
```

- 기본 설정: 메모리 256MB / 타임아웃 5s 권장

#### 2) `Consumer` 생성 (SQS 트리거)

- 이름 : `aram-consumer`
- 런타임 : Python 3.12
- Architecture: arm64(비용↓) 또는 x86_64
- Execution role: 위의 consumer 역할 선택
- 코드 업로드 : `consumer.py` 내용 넣기
- 핸들러 : `lambda_function.lambda_handler` 로 설정
- 환경 변수

```
REGION=ap-northeast-2
STATS_TABLE=aram-stats
S3_BUCKET=aram-app-bucket
S3_KEY=stats.json
```

- 기본 설정: 메모리 256MB / 타임아웃 5s 권장
- 트리거 연결
  - Lambda 콘솔 → aram-consumer → Add trigger → SQS aram-queue
  - Batch size: 10 (필요 시 조정) → Enable

### 6. API Gateway (HTTP) 연결

- HTTP API 생성 → 통합(Integration): Lambda = `aram-producer`
- 라우트 추가
  - `POST /api/book-bus` → `aram-producer`
  - `GET /api/stats` → `aram-producer`
- CORS
  - Origins: `*` (또는 S3 정적 호스팅 도메인만)
  - Methods: `GET,POST,OPTIONS`
  - Headers: `content-type`
- Stage: prod 생성 → **Invoke URL** 확보
  - 예: https://<HTTP_API_ID>.execute-api.ap-northeast-2.amazonaws.com/prod

### 7. Frontend / index.html 업데이트

- `index.html` 내 url 에 API Gateway주소, S3주소 적기

```javascript
const HTTP_API_BASE =
  "https://<HTTP_API_ID>.execute-api.ap-northeast-2.amazonaws.com/prod";
const STATS_S3_URL =
  "https://my-bus-app-bucket.s3.ap-northeast-2.amazonaws.com/stats.json";
```

- S3 버킷 my-bus-app-bucket에 index.html 업로드(덮어쓰기)
- 웹사이트 엔드포인트(HTTP)로 접속해 동작 확인

## 동작 검증

### 1. 브라우저에서 페이지 열기

- `HTTP API / Stats(S3)` 표시에 URL이 나오면 OK

### 2. 예매하기 버튼 여러 번 클릭

- 응답 200 + `{status:"queued"}` 유형이면 OK

### 3. 수초 내 지표 상승 확인

- `aram-consumer`가 SQS 메시지 처리→DynamoDB 갱신→같은 버킷의 `stats.json` 덮어쓰기
- `index.html`은 S3의 `stats.json`을 폴링하여 “총 처리/성공률” 업데이트

> 실패 시: Lambda CloudWatch Logs에서 에러 먼저 확인 (권한/환경변수 오타가 흔한 원인)

## 테스트

### 부하 테스트 실행

- artillery.yaml의 target을 HTTP API Invoke URL로 수정

```yaml
target: "https://<HTTP_API_ID>.execute-api.ap-northeast-2.amazonaws.com/prod"
```

- 실행 후 페이지에서 수치가 따라오는지 확인 (S3 폴링이 반영)

```shell
npx -y artillery@latest run artillery/artillery.yaml -o results.json
npx -y artillery@latest report results.json
```
