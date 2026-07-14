import { redirect } from "next/navigation";
import { cookies } from "next/headers";
import Link from "next/link";

const SESSION_COOKIE = "lm_session";

/** Root: redirect to dashboard if authenticated, otherwise show a lightweight landing. */
export default async function RootPage() {
  const cookieStore = await cookies();
  const hasSession = cookieStore.has(SESSION_COOKIE);

  if (hasSession) {
    redirect("/dashboard");
  }

  return (
    <div className="flex min-h-screen items-center justify-center px-4 bg-[#050607]">
      <div className="text-center max-w-md">
        <div className="mb-6 flex flex-col items-center gap-3">
          <span className="flex size-14 items-center justify-center rounded-[12px] bg-[#00f0a8] text-[#04120C] shadow-[0_0_30px_-4px_rgba(0,240,168,0.6)]">
            <span className="font-mono text-xl font-bold">L</span>
          </span>
          <h1 className="text-2xl font-bold text-white">LeadMine AI</h1>
          <p className="text-sm text-gray-400 mt-1">
            AI-driven B2B lead mining, enrichment, validation, and outreach.
          </p>
        </div>
        <Link
          href="/login"
          className="inline-flex items-center justify-center gap-2 px-6 py-3 rounded-lg bg-[#00f0a8] text-[#04120C] font-semibold text-sm hover:brightness-90 transition-all shadow-[0_0_20px_-4px_rgba(0,240,168,0.5)]"
        >
          Get Started
        </Link>
      </div>
    </div>
  );
}
