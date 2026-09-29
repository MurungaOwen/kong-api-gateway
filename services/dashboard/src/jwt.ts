import { createHmac } from "node:crypto";

const b64 = (o: object) => Buffer.from(JSON.stringify(o)).toString("base64url");

/** HS256 token Kong's jwt plugin accepts: `iss` selects the consumer credential, `exp` is required. */
export function signJwt(secret: string, issuer = "dashboard", ttlSeconds = 300, nowMs = Date.now()): string {
  const head = b64({ alg: "HS256", typ: "JWT" });
  const body = b64({ iss: issuer, exp: Math.floor(nowMs / 1000) + ttlSeconds });
  const sig = createHmac("sha256", secret).update(`${head}.${body}`).digest("base64url");
  return `${head}.${body}.${sig}`;
}
