import ForbiddenPage from "../forbidden/page";

type ForbiddenAliasPageProps = {
  searchParams?: Promise<{ from?: string; rid?: string; request_id?: string }>;
};

export default async function ForbiddenAliasPage({
  searchParams,
}: ForbiddenAliasPageProps) {
  return ForbiddenPage({ searchParams });
}
