// Node.js 22.x (ESM)
import {
  SQSClient,
  SendMessageCommand,
  GetQueueUrlCommand,
} from "@aws-sdk/client-sqs";
import {
  DynamoDBClient,
  UpdateItemCommand,
  GetItemCommand,
} from "@aws-sdk/client-dynamodb";

const REGION = process.env.AWS_REGION || process.env.REGION || "ap-northeast-2";
const STATS_TABLE = process.env.STATS_TABLE || "Stats";
const QUEUE_NAME = process.env.QUEUE_NAME || "";
const QUEUE_URL = process.env.QUEUE_URL || "";

const sqs = new SQSClient({ region: REGION });
const ddb = new DynamoDBClient({ region: REGION });

async function getQueueUrl() {
  if (QUEUE_URL) return QUEUE_URL;
  const out = await sqs.send(new GetQueueUrlCommand({ QueueName: QUEUE_NAME }));
  return out.QueueUrl;
}

async function incRequests() {
  await ddb.send(
    new UpdateItemCommand({
      TableName: STATS_TABLE,
      Key: { id: { S: "total" } },
      UpdateExpression: "ADD #r :one",
      ExpressionAttributeNames: { "#r": "requests" },
      ExpressionAttributeValues: { ":one": { N: "1" } },
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

export const handler = async (event) => {
  const method = event.requestContext?.http?.method || event.httpMethod;
  const path = event.requestContext?.http?.path || event.rawPath || "/";
  const headers = {
    "content-type": "application/json",
    "access-control-allow-origin": "*",
  };

  try {
    if (method === "GET" && path.endsWith("/api/stats")) {
      const stats = await getStats();
      return { statusCode: 200, headers, body: JSON.stringify(stats) };
    }

    if (method === "POST" && path.endsWith("/api/book-bus")) {
      const body =
        typeof event.body === "string"
          ? JSON.parse(event.body || "{}")
          : event.body || {};
      const QueueUrl = await getQueueUrl();
      await sqs.send(
        new SendMessageCommand({ QueueUrl, MessageBody: JSON.stringify(body) })
      );
      await incRequests();
      // 응답에 대략 최신 stats 포함 → UI가 즉시 1회 갱신 가능(선택)
      const stats = await getStats().catch(() => null);
      return {
        statusCode: 200,
        headers,
        body: JSON.stringify({ status: "queued", stats }),
      };
    }

    return {
      statusCode: 404,
      headers,
      body: JSON.stringify({ error: "not found" }),
    };
  } catch (e) {
    return {
      statusCode: 500,
      headers,
      body: JSON.stringify({ error: String(e) }),
    };
  }
};
