// day is the Toronto calendar date on which the 4 a.m. reporting window ends.
const clock = new Intl.DateTimeFormat("en-CA", {
  timeZone: "America/Toronto", year: "numeric", month: "2-digit", day: "2-digit",
  hour: "2-digit", hourCycle: "h23",
});
export function editionDay(now) {
  const parts = Object.fromEntries(clock.formatToParts(now).map(p => [p.type, p.value]));
  const d = new Date(Date.UTC(+parts.year, +parts.month - 1, +parts.day + (+parts.hour >= 4 ? 1 : 0)));
  return d.toISOString().slice(0, 10);
}
const origins = {
  "https://towardsai.com": ["main", "sales"],
  "https://www.towardsai.com": ["main", "sales"],
  "https://towardsai.net": ["main", "sales"],
  "https://www.towardsai.net": ["main", "sales"],
  "https://academy.towardsai.net": ["sales", "lessons"],
  "https://www.louisbouchard.ai": ["blog"],
  "https://louisbouchard.ai": ["blog"],
};
export default {
  async fetch(request, env) {
    const origin = request.headers.get("Origin");
    const allowed = origins[origin];
    if (new URL(request.url).pathname !== "/event" || !Array.isArray(allowed)) return new Response(null, {status:404});
    const headers = {"Access-Control-Allow-Origin":origin, Vary:"Origin","Cache-Control":"no-store"};
    const reply = status => new Response(null,{status,headers});
    if (request.method !== "POST") return reply(405);
    if (request.headers.get("Sec-GPC") === "1" || request.headers.get("DNT") === "1") return reply(204);
    if (!request.headers.get("Content-Type")?.startsWith("text/plain") || Number(request.headers.get("Content-Length") || 0) > 220) return reply(400);
    if (!(await env.INGEST_LIMIT.limit({key:request.headers.get("CF-Connecting-IP") || "unknown"})).success) return reply(429);
    const raw = await request.text();
    if (raw.length > 220) return reply(400);
    let event;
    try { event = JSON.parse(raw); } catch { return reply(400); }
    if (!event || !allowed.includes(event.surface) || ![1,2,3].includes(event.stage)
        || typeof event.visitor !== "string" || !/^[0-9a-f-]{36}$/.test(event.visitor)
        || event.day !== editionDay(new Date())) return reply(400);
    await env.DB.prepare(`INSERT INTO daily_visitors(day,surface,visitor,stage) VALUES(?,?,?,?)
      ON CONFLICT(day,surface,visitor) DO UPDATE SET stage=excluded.stage
      WHERE excluded.stage > daily_visitors.stage`).bind(event.day,event.surface,event.visitor,event.stage).run();
    return reply(204);
  },
  async scheduled(_event, env) {
    await env.DB.prepare("DELETE FROM daily_visitors WHERE day < date('now','-35 days')").run();
  },
};
