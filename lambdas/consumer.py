# filename: lambda_function.py
import os, json, boto3

REGION      = os.getenv("REGION", os.getenv("AWS_REGION", "ap-northeast-2"))
STATS_TABLE = os.environ["STATS_TABLE"]
S3_BUCKET   = os.environ["S3_BUCKET"]
S3_KEY      = os.getenv("S3_KEY", "stats.json")

dynamo = boto3.client("dynamodb", region_name=REGION)
s3     = boto3.client("s3", region_name=REGION)

def add_counters(processed=0, success=0):
    expr, names, values = [], {}, {}
    if processed:
        expr.append("ADD #p :p"); names["#p"]="processed"; values[":p"]={"N": str(processed)}
    if success:
        expr.append("ADD #s :s"); names["#s"]="success"; values[":s"]={"N": str(success)}
    if not expr: 
        return
    dynamo.update_item(
        TableName=STATS_TABLE,
        Key={"id": {"S": "total"}},
        UpdateExpression=" ".join(expr),
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
    s3.put_object(
        Bucket=S3_BUCKET,
        Key=S3_KEY,
        Body=json.dumps(stats).encode("utf-8"),
        ContentType="application/json",
        CacheControl="no-cache, no-store, must-revalidate",
    )

def lambda_handler(event, context):
    # SQS 이벤트
    records = event.get("Records") or []
    cnt = len(records)
    if cnt == 0:
        return {"ok": True, "processed": 0}

    # 여기서는 모두 성공 처리한다고 가정
    add_counters(processed=cnt, success=cnt)

    # 최신 스냅샷 생성
    stats = get_stats()
    write_stats_snapshot(stats)

    return {"ok": True, "processed": cnt}
