import os
import json
import hashlib
import boto3

REGION = os.getenv("REGION", os.getenv("AWS_REGION", "ap-northeast-2"))
STATS_TABLE = os.environ["STATS_TABLE"]
QUEUE_NAME  = os.getenv("QUEUE_NAME", "")
QUEUE_URL   = os.getenv("QUEUE_URL", "")

dynamo = boto3.client("dynamodb", region_name=REGION)
sqs    = boto3.client("sqs", region_name=REGION)


def _json(data, code=200):
    return {
        "statusCode": code,
        "headers": {
            "content-type": "application/json",
            "access-control-allow-origin": "*",
            "access-control-allow-methods": "GET,POST,OPTIONS",
            "access-control-allow-headers": "content-type",
        },
        "body": json.dumps(data),
    }


def _get_queue_url():
    if QUEUE_URL:
        return QUEUE_URL
    resp = sqs.get_queue_url(QueueName=QUEUE_NAME)
    return resp["QueueUrl"]


def _inc_requests():
    dynamo.update_item(
        TableName=STATS_TABLE,
        Key={"id": {"S": "total"}},
        UpdateExpression="ADD #r :one",
        ExpressionAttributeNames={"#r": "requests"},
        ExpressionAttributeValues={":one": {"N": "1"}},
    )


def _get_stats():
    resp = dynamo.get_item(
        TableName=STATS_TABLE,
        Key={"id": {"S": "total"}},
        ConsistentRead=True,
    )
    item = resp.get("Item", {})
    def n(k):
        v = item.get(k, {})
        return int(v.get("N", 0)) if "N" in v else 0
    return {"processed": n("processed"), "success": n("success"), "requests": n("requests")}


def _dedup_id(body: dict) -> str:
    """
    FIFO에서 content-based deduplication을 비활성화한 경우 필수.
    - 클라이언트가 requestId를 넘겨주면 그걸 사용(권장)
    - 없으면 body 전체를 정규화해서 해시 생성
    """
    rid = body.get("requestId")
    if rid:
        return str(rid)[:128]  # SQS 제한: 최대 128자
    blob = json.dumps(body, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode()).hexdigest()


def _message_group_id(body: dict) -> str:
    """
    좌석 단위로 순서 보장 & 병렬성 확보를 위한 그룹키.
    최소 tripId 단위라도 OK.
    """
    trip_id = body.get("tripId", "defaultTrip")
    seat_no = body.get("seatNo", "defaultSeat")
    return f"{trip_id}#{seat_no}"


def lambda_handler(event, context):
    # HTTP API v2 or v1 모두 커버
    method = (event.get("requestContext", {}).get("http", {}) or {}).get("method") or event.get("httpMethod")
    raw_path = (event.get("requestContext", {}).get("http", {}) or {}).get("path") or event.get("rawPath") or ""
    path = raw_path or (event.get("path") or "")

    if method == "OPTIONS":
        return _json({"ok": True}, 200)

    try:
        if method == "GET" and path.endswith("/api/stats"):
            return _json(_get_stats())

        if method == "POST" and path.endswith("/api/book-bus"):
            body = event.get("body")
            if isinstance(body, str):
                body = json.loads(body or "{}")
            elif body is None:
                body = {}

            queue_url = _get_queue_url()

            # FIFO 필수 필드들 (content-based dedup OFF 상태)
            message_group_id = _message_group_id(body)
            dedup_id = _dedup_id(body)

            sqs.send_message(
                QueueUrl=queue_url,
                MessageBody=json.dumps(body),
                MessageGroupId=message_group_id,
                MessageDeduplicationId=dedup_id,
            )

            _inc_requests()
            stats = _get_stats()  # UX 향상을 위해 최신 통계 반환
            return _json({"status": "queued", "stats": stats})

        return _json({"error": "not found"}, 404)
    except Exception as e:
        return _json({"error": str(e)}, 500)
