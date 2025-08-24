import os, json, boto3

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
            sqs.send_message(QueueUrl=queue_url, MessageBody=json.dumps(body))
            _inc_requests()
            # 선택: 바로 최신 통계 포함해 주면 UX 좋아짐
            stats = _get_stats()
            return _json({"status": "queued", "stats": stats})

        return _json({"error": "not found"}, 404)
    except Exception as e:
        return _json({"error": str(e)}, 500)
