import { redirect } from "next/navigation";

/** Root: the first screen is a product screen, never a marketing page. */
export default function RootPage() {
  redirect("/dashboard");
}
