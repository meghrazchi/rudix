import { SharedSessionPage } from "@/components/chat/SharedSessionPage";

type Props = {
  params: Promise<{ token: string }>;
};

export default async function SharedSessionRoutePage({ params }: Props) {
  const { token } = await params;
  return <SharedSessionPage token={token} />;
}
