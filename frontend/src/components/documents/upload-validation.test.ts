import { describe, expect, it } from "vitest";

import { validateUploadFile } from "@/components/documents/upload-validation";

describe("validateUploadFile", () => {
  it("accepts supported extension and mime type", () => {
    const file = new File(["content"], "guide.pdf", {
      type: "application/pdf",
    });
    expect(validateUploadFile(file, 25)).toBeNull();
  });

  it("rejects unsupported extension", () => {
    const file = new File(["content"], "script.exe", {
      type: "application/octet-stream",
    });
    expect(validateUploadFile(file, 25)).toMatch(/Unsupported file type/i);
  });

  it("rejects unsupported mime type", () => {
    const file = new File(["content"], "note.txt", {
      type: "application/json",
    });
    expect(validateUploadFile(file, 25)).toMatch(/Unsupported MIME type/i);
  });

  it("rejects empty files", () => {
    const file = new File([], "empty.txt", { type: "text/plain" });
    expect(validateUploadFile(file, 25)).toMatch(/File is empty/i);
  });

  it("rejects files larger than max size", () => {
    const largeBlob = new Uint8Array(2 * 1024 * 1024);
    const file = new File([largeBlob], "large.pdf", {
      type: "application/pdf",
    });
    expect(validateUploadFile(file, 1)).toMatch(/upload limit/i);
  });
});
