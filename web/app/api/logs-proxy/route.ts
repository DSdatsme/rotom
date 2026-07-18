import type { NextRequest } from "next/server";
import { getLogs } from "@/lib/api";

export const dynamic = "force-dynamic";

export async function GET(request: NextRequest) {
  const sp = request.nextUrl.searchParams;
  try {
    const data = await getLogs({
      level: sp.get("level") ?? undefined,
      kind: sp.get("kind") ?? undefined,
      run_id: sp.has("run_id") ? Number(sp.get("run_id")) : undefined,
      q: sp.get("q") ?? undefined,
      since: sp.get("since") ?? undefined,
      until: sp.get("until") ?? undefined,
      limit: sp.has("limit") ? Number(sp.get("limit")) : undefined,
      before_id: sp.has("before_id") ? Number(sp.get("before_id")) : undefined,
    });
    return Response.json(data);
  } catch (e) {
    return Response.json({ error: String(e) }, { status: 500 });
  }
}
