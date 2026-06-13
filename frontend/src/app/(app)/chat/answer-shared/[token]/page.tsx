import { SharedAnswerPage } from "@/components/chat/SharedAnswerPage";

type Props = {
  params: Promise<{ token: string }>;
};

export default async function SharedAnswerRoutePage({ params }: Props) {
  const { token } = await params;
  return <SharedAnswerPage token={token} />;
}
