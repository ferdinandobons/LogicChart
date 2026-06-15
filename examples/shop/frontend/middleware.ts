// Control: a single authentication guard (not a chain) - not flagged.
export function middleware(request: Request) {
  const token = request.headers.get("authorization");
  if (!token) {
    return new Response("unauthorized", { status: 401 });
  }
  return forward(request);
}
