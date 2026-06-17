import { AgentTraceReplayPage } from "@/components/workspace/AgentTraceReplayPage";

export default async function AgentTraceReplayRoutePage({
  params,
}: {
  params: Promise<{ runId: string }>;
}) {
  const { runId } = await params;
  return <AgentTraceReplayPage runId={runId} />;
}
