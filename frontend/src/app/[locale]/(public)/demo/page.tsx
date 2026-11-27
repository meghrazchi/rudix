import { redirect } from "next/navigation";

import { useRequestLocale } from "@/i18n/request-locale";

type DemoAliasPageProps = {
  params?: Promise<{ locale: string }>;
};

export default function DemoAliasPage({ params }: DemoAliasPageProps = {}) {
  useRequestLocale(params);
  redirect("/contact");
}
