import { redirect } from "next/navigation";

/**
 * Self-service registration is disabled: accounts are created by workspace
 * administrators (team invitations, SCIM, or SSO). The route stays as a
 * redirect so old links and bookmarks land on sign-in instead of a 404.
 */
export default function SignupAliasPage() {
  redirect("/login");
}
