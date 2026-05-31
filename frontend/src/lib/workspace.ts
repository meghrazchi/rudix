import type { AppRole } from "@/lib/auth-session";

export function orgInitials(name: string): string {
  const trimmed = name.trim();
  if (!trimmed) return "W";
  const words = trimmed.split(/\s+/).filter(Boolean);
  if (words.length === 1) {
    return (words[0] ?? "W").slice(0, 2).toUpperCase();
  }
  return `${words[0]?.[0] ?? ""}${words[1]?.[0] ?? ""}`.toUpperCase();
}

const AVATAR_PALETTE = [
  { bg: "#ece9ff", text: "#3525cd" },
  { bg: "#dbeafe", text: "#1d4ed8" },
  { bg: "#d1fae5", text: "#065f46" },
  { bg: "#fce7f3", text: "#9d174d" },
  { bg: "#fef3c7", text: "#92400e" },
  { bg: "#e0e7ff", text: "#3730a3" },
  { bg: "#fde8d0", text: "#7c2d12" },
  { bg: "#f3e8ff", text: "#7e22ce" },
] as const;

export function orgAvatarColor(name: string): { bg: string; text: string } {
  if (!name.trim()) return AVATAR_PALETTE[0];
  const hash = name
    .split("")
    .reduce((acc, char) => (acc * 31 + char.charCodeAt(0)) >>> 0, 0);
  return AVATAR_PALETTE[hash % AVATAR_PALETTE.length] ?? AVATAR_PALETTE[0];
}

export function orgPlanLabel(plan: string | null | undefined): string | null {
  if (!plan) return null;
  const normalized = plan.trim().toLowerCase();
  const LABELS: Record<string, string> = {
    free: "Free",
    starter: "Starter",
    pro: "Pro",
    professional: "Pro",
    enterprise: "Enterprise",
    trial: "Trial",
    business: "Business",
  };
  return LABELS[normalized] ?? plan.trim();
}

export function roleDisplayLabel(role: AppRole): string {
  const LABELS: Record<AppRole, string> = {
    owner: "Owner",
    admin: "Admin",
    member: "Member",
    viewer: "Viewer",
  };
  return LABELS[role] ?? role;
}

export function buildSwitchWorkspaceUrl(currentPath: string): string {
  const params = new URLSearchParams({ reason: "workspace_switch" });
  const safePath =
    currentPath.startsWith("/") && !currentPath.startsWith("/login")
      ? currentPath
      : "/";
  if (safePath !== "/") {
    params.set("next", safePath);
  }
  return `/login?${params.toString()}`;
}
