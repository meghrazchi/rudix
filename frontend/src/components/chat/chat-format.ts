export function formatDate(value: string): string {
  try {
    return new Date(value).toLocaleString();
  } catch {
    return value;
  }
}

export function formatScore(value: number | null | undefined): string {
  if (typeof value !== "number" || Number.isNaN(value)) {
    return "N/A";
  }
  return value.toFixed(3);
}

export function normalizeScorePercent(
  value: number | null | undefined,
): number | null {
  if (typeof value !== "number" || Number.isNaN(value)) {
    return null;
  }
  const percent = value <= 1 ? value * 100 : value;
  return Math.min(100, Math.max(0, percent));
}

export function formatScorePercent(value: number | null | undefined): string {
  const percent = normalizeScorePercent(value);
  return percent === null ? "N/A" : `${percent.toFixed(1)}%`;
}

export function triggerBlobDownload(blob: Blob, filename: string): void {
  const objectUrl = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = objectUrl;
  anchor.download = filename;
  anchor.rel = "noopener";
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(objectUrl);
}

export function getFileIcon(filename: string | null | undefined): string {
  if (!filename) return "draft";
  const ext = filename.split(".").pop()?.toLowerCase() ?? "";
  if (ext === "pdf") return "picture_as_pdf";
  if (["doc", "docx"].includes(ext)) return "description";
  if (["md", "txt"].includes(ext)) return "text_snippet";
  if (["xlsx", "xls"].includes(ext)) return "table_chart";
  if (["csv"].includes(ext)) return "dataset";
  if (["png", "jpg", "jpeg", "gif", "svg", "webp"].includes(ext))
    return "image";
  if (["mp4", "mov", "avi", "webm"].includes(ext)) return "videocam";
  if (["mp3", "wav", "ogg"].includes(ext)) return "audio_file";
  if (["zip", "tar", "gz", "rar"].includes(ext)) return "folder_zip";
  if (["json", "xml", "yaml", "yml"].includes(ext)) return "data_object";
  if (["js", "ts", "py", "java", "go", "rs", "cpp", "c", "cs"].includes(ext))
    return "code";
  if (["pptx", "ppt"].includes(ext)) return "slideshow";
  return "draft";
}

export function getFileTypeLabel(filename: string | null | undefined): string {
  if (!filename) return "FILE";
  return filename.split(".").pop()?.toUpperCase() ?? "FILE";
}

export function getFileTypeColorClass(
  filename: string | null | undefined,
): string {
  if (!filename) return "text-[#464555]";
  const ext = filename.split(".").pop()?.toLowerCase() ?? "";
  if (ext === "pdf") return "text-[#3525cd]";
  if (["md", "txt", "doc", "docx"].includes(ext)) return "text-emerald-600";
  if (["xlsx", "xls", "csv"].includes(ext)) return "text-amber-600";
  return "text-[#464555]";
}

export function isPreviewableFile(
  filename: string | null | undefined,
): boolean {
  if (!filename) return false;
  const ext = filename.split(".").pop()?.toLowerCase() ?? "";
  return ext === "pdf" || ext === "docx" || ext === "doc";
}
