import {
  DynamoDBClient,
  UpdateItemCommand,
  GetItemCommand,
} from "@aws-sdk/client-dynamodb";
import { S3Client, PutObjectCommand } from "@aws-sdk/client-s3";

const REGION = process.env.AWS_REGION || process.env.REGION || "ap-northeast-2";
const STATS_TABLE = process.env.STATS_TABLE || "Stats";
const S3_BUCKET = process.env.S3_BUCKET || ""; // 예: bus-booking-stats
const S3_KEY = process.env.S3_KEY || "stats.json"; // 예: stats.json

const ddb = new DynamoDBClient({ region: REGION });
const s3 = new S3Client({ region: REGION });

async function addCounters({ processed = 0, success = 0 }) {
  const parts = [],
    names = {},
    values = {};
  if (processed) {
    parts.push("ADD #p :p");
    names["#p"] = "processed";
    values[":p"] = { N: String(processed) };
  }
  if (success) {
    parts.push("ADD #s :s");
    names["#s"] = "success";
    values[":s"] = { N: String(success) };
  }
  if (!parts.length) return;
  await ddb.send(
    new UpdateItemCommand({
      TableName: STATS_TABLE,
      Key: { id: { S: "total" } },
      UpdateExpression: parts.join(" "),
      ExpressionAttributeNames: names,
      ExpressionAttributeValues: values,
    })
  );
}

async function getStats() {
  const out = await ddb.send(
    new GetItemCommand({
      TableName: STATS_TABLE,
      Key: { id: { S: "total" } },
      ConsistentRead: true,
    })
  );
  const n = (k) => Number(out.Item?.[k]?.N ?? 0);
  return {
    processed: n("processed"),
    success: n("success"),
    requests: n("requests"),
  };
}

async function writeStatsSnapshot(stats) {
  if (!S3_BUCKET) return;
  await s3.send(
    new PutObjectCommand({
      Bucket: S3_BUCKET,
      Key: S3_KEY,
      Body: JSON.stringify(stats),
      ContentType: "application/json",
      CacheControl: "no-cache, no-store, must-revalidate",
    })
  );
}

export const handler = async (event) => {
  const count = (event.Records || []).length;
  if (!count) return { ok: true };

  // 여기서는 모든 메시지를 성공 처리한다고 가정 (실서비스 로직에 맞게 조정)
  await addCounters({ processed: count, success: count });

  // 최신 스냅샷 생성 → S3 업로드
  const stats = await getStats().catch(() => null);
  if (stats) await writeStatsSnapshot(stats);

  return { ok: true, processed: count };
};
