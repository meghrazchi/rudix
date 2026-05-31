import type { ChatCitationResponse, ChatSessionMessageResponse } from "@/lib/api/chat";

export type ExportTurn = {
  question: string;
  answer: string;
  citations: ChatCitationResponse[];
  created_at: string;
};

function citationBlock(citations: ChatCitationResponse[]): string {
  if (citations.length === 0) return "";
  const lines = citations.map((c, i) => {
    let line = `${i + 1}. **${c.filename ?? "Document"}**`;
    if (c.page_number != null) line += ` (page ${c.page_number})`;
    if (c.text_snippet) line += `\n   > ${c.text_snippet}`;
    return line;
  });
  return `\n\n**Sources**\n\n${lines.join("\n")}\n`;
}

export function formatTurnAsMarkdown(turn: ExportTurn): string {
  let md = `**Q:** ${turn.question}\n\n`;
  md += `> *AI-generated answer*\n\n${turn.answer}`;
  md += citationBlock(turn.citations);
  return md;
}

export function formatTranscriptAsMarkdown(
  turns: ExportTurn[],
  sessionTitle: string | null | undefined,
): string {
  const title = sessionTitle?.trim() || "Chat Export";
  const header = [
    `# ${title}`,
    "",
    `*Exported from Rudix. AI-generated answers are grounded in cited source evidence.*`,
    "",
    "---",
    "",
  ].join("\n");

  const body = turns
    .map((turn, i) => `## Turn ${i + 1}\n\n${formatTurnAsMarkdown(turn)}`)
    .join("\n\n---\n\n");

  return header + body + "\n";
}

export function formatAnswerAsMarkdown(turn: ExportTurn): string {
  let md = turn.answer;
  md += citationBlock(turn.citations);
  return md;
}

export function formatSourceListAsMarkdown(turns: ExportTurn[]): string {
  const seen = new Set<string>();
  const unique: ChatCitationResponse[] = [];
  for (const turn of turns) {
    for (const c of turn.citations) {
      const key = `${c.document_id}:${c.chunk_id}`;
      if (!seen.has(key)) {
        seen.add(key);
        unique.push(c);
      }
    }
  }
  if (unique.length === 0) return "No sources cited.\n";
  const lines = unique.map((c, i) => {
    let line = `${i + 1}. **${c.filename ?? "Document"}**`;
    if (c.page_number != null) line += ` — page ${c.page_number}`;
    return line;
  });
  return `# Source List\n\n${lines.join("\n")}\n`;
}

export function turnsFromMessages(messages: ChatSessionMessageResponse[]): ExportTurn[] {
  const turns: ExportTurn[] = [];
  let lastQuestion: string | null = null;
  for (const msg of messages) {
    if (msg.role === "user") {
      lastQuestion = msg.content;
    } else if (msg.role === "assistant" && lastQuestion !== null) {
      turns.push({
        question: lastQuestion,
        answer: msg.content,
        citations: msg.citations ?? [],
        created_at: msg.created_at,
      });
      lastQuestion = null;
    }
  }
  return turns;
}

export async function copyToClipboard(text: string): Promise<void> {
  await navigator.clipboard.writeText(text);
}

export function downloadMarkdown(text: string, filename: string): void {
  const blob = new Blob([text], { type: "text/markdown; charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

export function sanitizeFilename(name: string): string {
  return name.replace(/[^a-z0-9_\-. ]/gi, "_").slice(0, 80) || "export";
}
