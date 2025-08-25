import os, json, boto3
from typing import List

REGION      = os.getenv("REGION", os.getenv("AWS_REGION", "ap-northeast-2"))
STATS_TABLE = os.getenv("STATS_TABLE")
S3_BUCKET   = os.getenv("S3_BUCKET")
S3_KEY      = os.getenv("S3_KEY", "stats.json")

dynamo = boto3.client("dynamodb", region_name=REGION)
s3     = boto3.client("s3", region_name=REGION)

def add_counters(processed=0, success=0):
    parts, names, values = [], {}, {}
    if processed:
        parts.append("#p :p"); names["#p"] = "processed"; values[":p"] = {"N": str(processed)}
    if success:
        parts.append("#s :s"); names["#s"] = "success";   values[":s"] = {"N": str(success)}
    if not parts:
        return
    # ✅ 여러 속성 증분은 ADD 절을 '한 번'만 쓰고 콤마로 구분
    update_expr = "ADD " + ", ".join(parts)
    dynamo.update_item(
        TableName=STATS_TABLE,
        Key={"id": {"S": "total"}},
        UpdateExpression=update_expr,
        ExpressionAttributeNames=names,
        ExpressionAttributeValues=values,
    )

def get_stats():
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

def write_stats_snapshot(stats: dict):
    if not S3_BUCKET:
        print("[WARN] S3_BUCKET not set; skip snapshot")
        return
    try:
        s3.put_object(
            Bucket=S3_BUCKET,
            Key=S3_KEY,
            Body=json.dumps(stats).encode("utf-8"),
            ContentType="application/json",
            CacheControl="no-cache, no-store, must-revalidate",
        )
        print(f"[OK] wrote s3://{S3_BUCKET}/{S3_KEY}")
    except Exception as e:
        # 스냅샷 실패가 배치 전체 실패를 유발하지 않도록
        print(f"[ERROR] write_stats_snapshot failed: {e}")

# === 실제 처리 로직 자리 (성공 시 예외 없음, 재시도 필요 시 예외 발생) ===
def process_booking(msg: dict) -> None:
    # TODO: 좌석 확정/결제/조건부 갱신 등
    return

def lambda_handler(event, context):
    records: List[dict] = event.get("Records") or []
    if not records:
        return {"ok": True, "processed": 0, "batchItemFailures": []}

    success_ids: List[str] = []
    failure_ids: List[str] = []

    for r in records:
        msg_id = r.get("messageId")
        body = r.get("body")
        try:
            data = json.loads(body) if isinstance(body, str) else (body or {})
        except Exception as e:
            print(f"[ERROR] JSON parse failed for {msg_id}: {e}")
            if msg_id: failure_ids.append(msg_id)
            continue

        try:
            process_booking(data)
            if msg_id: success_ids.append(msg_id)
        except Exception as e:
            print(f"[ERROR] process_booking failed for {msg_id}: {e}")
            if msg_id: failure_ids.append(msg_id)

    # ✅ 여기서 ValidationException 발생하던 부분이 해결됨
    add_counters(processed=len(records), success=len(success_ids))

    stats = get_stats()
    write_stats_snapshot(stats)

    print(f"[INFO] processed={len(records)} success={len(success_ids)} failed={len(failure_ids)}")
    return {
        "ok": True,
        "processed": len(records),
        "succeeded": len(success_ids),
        "failed": len(failure_ids),
        "batchItemFailures": [{"itemIdentifier": fid} for fid in failure_ids],
    }
