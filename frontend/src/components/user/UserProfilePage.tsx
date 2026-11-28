"use client";

import { AccountActionsSection } from "@/components/user/profile/AccountActionsSection";
import { AccountIdentitySection } from "@/components/user/profile/AccountIdentitySection";
import { PersonalPreferencesSection } from "@/components/user/profile/PersonalPreferencesSection";
import { ProfileActionBar } from "@/components/user/profile/ProfileActionBar";
import { ProfileDialogs } from "@/components/user/profile/ProfileDialogs";
import { ProfileToast } from "@/components/user/profile/ProfileToast";
import { RagDefaultsSection } from "@/components/user/profile/RagDefaultsSection";
import { useUserProfileController } from "@/components/user/profile/useUserProfileController";

export function UserProfilePage() {
  const ctl = useUserProfileController();

  return (
    <>
      <ProfileDialogs ctl={ctl} />

      <div className="grid grid-cols-1 gap-8 lg:grid-cols-12">
        <div className="space-y-6 lg:col-span-7">
          <AccountIdentitySection ctl={ctl} />
          <PersonalPreferencesSection ctl={ctl} />
        </div>

        <div className="space-y-6 lg:col-span-5">
          <RagDefaultsSection ctl={ctl} />
        </div>
      </div>

      <ProfileActionBar ctl={ctl} />
      <AccountActionsSection ctl={ctl} />
      <ProfileToast ctl={ctl} />
    </>
  );
}
