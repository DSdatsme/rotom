import type { NextRequest } from "next/server";
import { getRuns } from "@/lib/api";

export const dynamic = "force-dynamic";

export async function GET(request: NextRequest) {
  const limit = Number(request.nextUrl.searchParams.get("limit") ?? "50");
  const source = request.nextUrl.searchParams.get("source") ?? undefined;
  const kind = request.nextUrl.searchParams.get("kind") ?? undefined;
  try {
    const data = await getRuns(Math.min(limit, 200), { source, kind });
    return Response.json(data);
  } catch (e) {
    return Response.json({ error: String(e) }, { status: 500 });
  }
}
