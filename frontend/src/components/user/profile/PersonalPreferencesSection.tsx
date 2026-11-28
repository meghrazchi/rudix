"use client";

import { SlidersHorizontal } from "lucide-react";
import { ContextualHelpLink } from "@/components/help/ContextualHelpLink";
import {
  LANGUAGE_OPTIONS,
  THEME_OPTIONS,
  TIMEZONE_OPTIONS,
} from "@/lib/schemas/settings";
import { THEME_ICONS } from "@/components/user/profile/profileShared";
import { useUserProfileController } from "@/components/user/profile/useUserProfileController";

export function PersonalPreferencesSection({
  ctl,
}: {
  ctl: ReturnType<typeof useUserProfileController>;
}) {
  const { t, personalForm, watchedTheme, themeLabel } = ctl;

  return (
    <>
      <section
        className="rounded-2xl border border-[#c7c4d8] bg-white p-6"
        aria-label={t("aria.personalPreferencesSection")}
      >
        <div className="mb-6 flex items-center gap-3">
          <SlidersHorizontal size={20} className="text-[#3525cd]" />
          <h3 className="text-lg font-semibold text-[#1b1b24]">
            {t("personalPreferences")}
          </h3>
        </div>

        <div className="grid grid-cols-1 gap-6 md:grid-cols-2">
          <div className="space-y-1">
            <div className="flex items-center gap-2">
              <label
                htmlFor="language"
                className="block text-[10px] font-semibold tracking-widest text-[#464555] uppercase"
              >
                {t("displayLanguage")}
              </label>
              <ContextualHelpLink topic="multilingual" />
            </div>
            <select
              id="language"
              {...personalForm.register("language")}
              className="w-full max-w-full appearance-none rounded-xl border border-[#c7c4d8] bg-[#fcf8ff] px-4 py-2 text-start text-sm text-[#1b1b24] outline-none focus:border-[#3525cd] focus:ring-2 focus:ring-[#3525cd]/10"
            >
              {LANGUAGE_OPTIONS.map((opt) => (
                <option key={opt.value} value={opt.value}>
                  {opt.label}
                </option>
              ))}
            </select>
          </div>

          <div className="space-y-1">
            <label
              htmlFor="timezone"
              className="block text-[10px] font-semibold tracking-widest text-[#464555] uppercase"
            >
              {t("timezone")}
            </label>
            <select
              id="timezone"
              {...personalForm.register("timezone")}
              className="w-full max-w-full appearance-none rounded-xl border border-[#c7c4d8] bg-[#fcf8ff] px-4 py-2 text-start text-sm text-[#1b1b24] outline-none focus:border-[#3525cd] focus:ring-2 focus:ring-[#3525cd]/10"
            >
              {TIMEZONE_OPTIONS.map((opt) => (
                <option key={opt.value} value={opt.value}>
                  {opt.label}
                </option>
              ))}
            </select>
          </div>
        </div>

        {/* Theme picker */}
        <div className="mt-6">
          <p className="mb-3 block text-[10px] font-semibold tracking-widest text-[#464555] uppercase">
            {t("interfaceTheme")}
          </p>
          <div className="grid grid-cols-3 gap-4">
            {THEME_OPTIONS.map((opt) => {
              const Icon = THEME_ICONS[opt];
              const isActive = watchedTheme === opt;
              return (
                <label
                  key={opt}
                  className={[
                    "flex cursor-pointer flex-col items-center gap-2 rounded-2xl border-2 p-4 transition-all",
                    isActive
                      ? "border-[#3525cd] bg-[#3525cd]/5"
                      : "border-transparent bg-[#f0ecf9] hover:border-[#c7c4d8]",
                  ].join(" ")}
                >
                  <input
                    type="radio"
                    {...personalForm.register("theme")}
                    value={opt}
                    className="sr-only"
                  />
                  <Icon
                    size={20}
                    className={isActive ? "text-[#3525cd]" : "text-[#464555]"}
                  />
                  <span
                    className={[
                      "text-sm",
                      isActive ? "font-bold text-[#3525cd]" : "text-[#464555]",
                    ].join(" ")}
                  >
                    {themeLabel[opt]}
                  </span>
                </label>
              );
            })}
          </div>
        </div>
      </section>
    </>
  );
}
