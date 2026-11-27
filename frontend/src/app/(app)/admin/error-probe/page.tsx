import { notFound } from "next/navigation";

// Test-only route (R07-08): throws during render so e2e can prove that a
// segment error keeps the app shell usable. It is 404 unless the build sets
// NEXT_PUBLIC_E2E_ERROR_PROBE=true, which staging/production builds refuse.
// Not listed in navigation.
export default function AdminErrorProbePage() {
  if (process.env.NEXT_PUBLIC_E2E_ERROR_PROBE !== "true") {
    notFound();
  }
  throw new Error("E2E error probe: intentional render failure");
}
