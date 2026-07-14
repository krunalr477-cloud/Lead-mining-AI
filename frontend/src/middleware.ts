import { NextRequest, NextResponse } from "next/server";

const SESSION_COOKIE = "lm_session";

/** Paths that render without a session. */
const PUBLIC_PATHS = ["/login", "/"];

/**
 * Redirect unauthenticated users to /login. Presence of the httpOnly
 * `lm_session` cookie is the gate — the backend owns issuance/validation; the
 * middleware only checks existence to avoid rendering the app shell logged out.
 */
export function middleware(req: NextRequest) {
  const { pathname } = req.nextUrl;
  const hasSession = req.cookies.has(SESSION_COOKIE);

  const isPublic = PUBLIC_PATHS.some((p) => pathname === p || pathname.startsWith(`${p}/`));

  if (!hasSession && !isPublic) {
    const loginUrl = new URL("/login", req.url);
    // Preserve intended destination for post-login redirect.
    if (pathname !== "/" && pathname !== "/login") loginUrl.searchParams.set("next", pathname);
    return NextResponse.redirect(loginUrl);
  }

  // Signed-in users hitting /login or / go to the dashboard.
  if (hasSession && (pathname === "/login" || pathname === "/")) {
    return NextResponse.redirect(new URL("/dashboard", req.url));
  }

  return NextResponse.next();
}

export const config = {
  /**
   * Run on everything except Next internals, the API proxy (handled by the
   * backend), and static assets.
   */
  matcher: ["/((?!api|_next/static|_next/image|favicon.ico|.*\\.svg$).*)"],
};
