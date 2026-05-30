import { apiRequest } from "@/lib/api/request";

function trimToNull(value: string | undefined): string | null {
  if (!value) {
    return null;
  }
  const trimmed = value.trim();
  return trimmed.length > 0 ? trimmed : null;
}

export type ProfileCapabilities = {
  signOutAllDevicesEnabled: boolean;
  deleteAccountEnabled: boolean;
};

export function getProfileCapabilities(): ProfileCapabilities {
  return {
    signOutAllDevicesEnabled:
      trimToNull(process.env.NEXT_PUBLIC_PROFILE_SIGN_OUT_ALL_URL) !== null,
    deleteAccountEnabled:
      trimToNull(process.env.NEXT_PUBLIC_PROFILE_DELETE_ACCOUNT_URL) !== null,
  };
}

export async function signOutAllDevices(): Promise<void> {
  const url = trimToNull(process.env.NEXT_PUBLIC_PROFILE_SIGN_OUT_ALL_URL);
  if (!url) {
    throw new Error("Sign out all devices endpoint is not configured.");
  }
  await apiRequest(url, { method: "POST", retry: false });
}

export async function deletePersonalAccount(): Promise<void> {
  const url = trimToNull(process.env.NEXT_PUBLIC_PROFILE_DELETE_ACCOUNT_URL);
  if (!url) {
    throw new Error("Delete account endpoint is not configured.");
  }
  await apiRequest(url, { method: "DELETE", retry: false });
}
