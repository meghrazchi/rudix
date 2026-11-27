import ForbiddenPage from "../forbidden/page";

type ForbiddenAliasPageProps = {
  params?: Promise<{ locale: string }>;
  searchParams?: Promise<{ from?: string; rid?: string; request_id?: string }>;
};

export default async function ForbiddenAliasPage({
  params,
  searchParams,
}: ForbiddenAliasPageProps) {
  return ForbiddenPage({ params, searchParams });
}
