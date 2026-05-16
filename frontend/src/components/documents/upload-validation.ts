const DEFAULT_MAX_UPLOAD_SIZE_MB = 25;

export const ACCEPTED_UPLOAD_EXTENSIONS = [".pdf", ".txt", ".docx"] as const;
export const ACCEPTED_UPLOAD_MIME_TYPES = new Set([
  "application/pdf",
  "text/plain",
  "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
]);
export const ACCEPTED_UPLOAD_TYPES_LABEL = "PDF, TXT, DOCX";

function parsePositiveIntegerEnv(value: string | undefined, fallback: number): number {
  if (!value) {
    return fallback;
  }

  const parsed = Number.parseInt(value, 10);
  if (!Number.isFinite(parsed) || parsed <= 0) {
    return fallback;
  }
  return parsed;
}

function normalizeMimeType(value: string): string {
  const trimmed = value.trim().toLowerCase();
  const semicolonIndex = trimmed.indexOf(";");
  if (semicolonIndex === -1) {
    return trimmed;
  }
  return trimmed.slice(0, semicolonIndex).trim();
}

function fileExtension(filename: string): string {
  const parts = filename.toLowerCase().split(".");
  if (parts.length < 2) {
    return "";
  }
  return `.${parts[parts.length - 1]}`;
}

export function maxUploadSizeMbFromEnv(): number {
  return parsePositiveIntegerEnv(process.env.NEXT_PUBLIC_MAX_UPLOAD_SIZE_MB, DEFAULT_MAX_UPLOAD_SIZE_MB);
}

export function validateUploadFile(file: File, maxUploadSizeMb: number): string | null {
  const extension = fileExtension(file.name);
  if (!ACCEPTED_UPLOAD_EXTENSIONS.includes(extension as (typeof ACCEPTED_UPLOAD_EXTENSIONS)[number])) {
    return `Unsupported file type. Use ${ACCEPTED_UPLOAD_TYPES_LABEL}.`;
  }

  if (file.size <= 0) {
    return "File is empty. Select a non-empty file.";
  }

  const maxBytes = maxUploadSizeMb * 1024 * 1024;
  if (file.size > maxBytes) {
    return `File exceeds the ${maxUploadSizeMb} MB upload limit.`;
  }

  if (file.type) {
    const mimeType = normalizeMimeType(file.type);
    if (!ACCEPTED_UPLOAD_MIME_TYPES.has(mimeType)) {
      return `Unsupported MIME type (${mimeType}). Use ${ACCEPTED_UPLOAD_TYPES_LABEL}.`;
    }
  }

  return null;
}
