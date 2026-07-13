import { ReportSectionPage } from "@/components/reports/ReportSectionPage";

export default async function ReportPage({
  params,
}: {
  params: Promise<{ section: string }>;
}) {
  const { section } = await params;
  return <ReportSectionPage slug={section} />;
}
