import { describe, expect, it } from "vitest";

import {
  updateModelProviderSettingsSchema,
  modelProviderSettingsResponseSchema,
  effectiveModelProviderPolicySchema,
  modelProviderChangeLogResponseSchema,
} from "@/lib/schemas/model-provider-settings";

// ── updateModelProviderSettingsSchema ─────────────────────────────────────────

describe("updateModelProviderSettingsSchema", () => {
  it("accepts a full valid payload", () => {
    const result = updateModelProviderSettingsSchema.safeParse({
      provider: "openai",
      llm_model: "gpt-4o",
      embedding_model: "text-embedding-3-small",
      max_tokens: 4096,
      timeout_seconds: 30,
      max_retries: 2,
      fallback_model: "gpt-3.5-turbo",
      disabled_models: ["davinci"],
      change_note: "Initial config",
    });
    expect(result.success).toBe(true);
  });

  it("accepts a partial payload with a single field", () => {
    const result = updateModelProviderSettingsSchema.safeParse({
      llm_model: "gpt-4o-mini",
    });
    expect(result.success).toBe(true);
  });

  it("accepts change_note-only payload with another field present", () => {
    const result = updateModelProviderSettingsSchema.safeParse({
      llm_model: "gpt-4o",
      change_note: "Updated model",
    });
    expect(result.success).toBe(true);
  });

  it("trims whitespace from provider", () => {
    const result = updateModelProviderSettingsSchema.safeParse({
      provider: "  openai  ",
    });
    expect(result.success).toBe(true);
    if (result.success) {
      expect(result.data.provider).toBe("openai");
    }
  });

  it("rejects blank provider string", () => {
    const result = updateModelProviderSettingsSchema.safeParse({
      provider: "   ",
    });
    expect(result.success).toBe(false);
  });

  it("rejects max_retries above 10", () => {
    const result = updateModelProviderSettingsSchema.safeParse({
      max_retries: 99,
    });
    expect(result.success).toBe(false);
  });

  it("rejects max_retries below 0", () => {
    const result = updateModelProviderSettingsSchema.safeParse({
      max_retries: -1,
    });
    expect(result.success).toBe(false);
  });

  it("rejects max_tokens below 1", () => {
    const result = updateModelProviderSettingsSchema.safeParse({
      max_tokens: 0,
    });
    expect(result.success).toBe(false);
  });

  it("rejects duplicate disabled_models entries", () => {
    const result = updateModelProviderSettingsSchema.safeParse({
      disabled_models: ["gpt-3.5-turbo", "gpt-3.5-turbo"],
    });
    expect(result.success).toBe(false);
  });

  it("rejects blank entries in disabled_models", () => {
    const result = updateModelProviderSettingsSchema.safeParse({
      disabled_models: ["  "],
    });
    expect(result.success).toBe(false);
  });

  it("accepts null disabled_models to clear the list", () => {
    const result = updateModelProviderSettingsSchema.safeParse({
      disabled_models: null,
      llm_model: "gpt-4o",
    });
    expect(result.success).toBe(true);
  });

  it("accepts an empty disabled_models array", () => {
    const result = updateModelProviderSettingsSchema.safeParse({
      disabled_models: [],
      llm_model: "gpt-4o",
    });
    expect(result.success).toBe(true);
  });
});

// ── modelProviderSettingsResponseSchema ───────────────────────────────────────

describe("modelProviderSettingsResponseSchema", () => {
  it("accepts a full valid response", () => {
    const result = modelProviderSettingsResponseSchema.safeParse({
      organization_id: "org-123",
      provider: "openai",
      llm_model: "gpt-4o",
      embedding_model: "text-embedding-3-small",
      max_tokens: 4096,
      timeout_seconds: 30,
      max_retries: 2,
      fallback_model: "gpt-3.5-turbo",
      disabled_models: [],
      llm_key_configured: true,
      version: 3,
      updated_by_id: "user-abc",
      updated_at: "2026-06-05T00:00:00Z",
    });
    expect(result.success).toBe(true);
  });

  it("accepts null optional fields", () => {
    const result = modelProviderSettingsResponseSchema.safeParse({
      organization_id: "org-123",
      provider: null,
      llm_model: null,
      embedding_model: null,
      max_tokens: null,
      timeout_seconds: null,
      max_retries: null,
      fallback_model: null,
      disabled_models: [],
      llm_key_configured: false,
      version: 1,
      updated_by_id: null,
      updated_at: "2026-06-05T00:00:00Z",
    });
    expect(result.success).toBe(true);
  });

  it("does not accept raw API key fields", () => {
    // Ensure the schema has no openai_api_key field
    const keys = Object.keys(
      modelProviderSettingsResponseSchema.shape,
    );
    expect(keys).not.toContain("openai_api_key");
    expect(keys).not.toContain("api_key");
  });
});

// ── effectiveModelProviderPolicySchema ────────────────────────────────────────

describe("effectiveModelProviderPolicySchema", () => {
  it("accepts org_override source", () => {
    const result = effectiveModelProviderPolicySchema.safeParse({
      organization_id: "org-1",
      provider: "openai",
      llm_model: "gpt-4o",
      embedding_model: "text-embedding-3-small",
      max_tokens: null,
      timeout_seconds: 30,
      max_retries: 2,
      fallback_model: null,
      disabled_models: [],
      llm_key_configured: true,
      source: "org_override",
      version: 1,
    });
    expect(result.success).toBe(true);
  });

  it("accepts system_default source", () => {
    const result = effectiveModelProviderPolicySchema.safeParse({
      organization_id: "org-1",
      provider: "openai",
      llm_model: "gpt-4o",
      embedding_model: "text-embedding-3-small",
      max_tokens: null,
      timeout_seconds: 30,
      max_retries: 2,
      fallback_model: null,
      disabled_models: [],
      llm_key_configured: true,
      source: "system_default",
      version: 0,
    });
    expect(result.success).toBe(true);
  });

  it("rejects unknown source value", () => {
    const result = effectiveModelProviderPolicySchema.safeParse({
      organization_id: "org-1",
      provider: "openai",
      llm_model: "gpt-4o",
      embedding_model: "text-embedding-3-small",
      max_tokens: null,
      timeout_seconds: 30,
      max_retries: 2,
      fallback_model: null,
      disabled_models: [],
      llm_key_configured: true,
      source: "custom",
      version: 0,
    });
    expect(result.success).toBe(false);
  });
});

// ── modelProviderChangeLogResponseSchema ──────────────────────────────────────

describe("modelProviderChangeLogResponseSchema", () => {
  it("accepts a valid change log response", () => {
    const result = modelProviderChangeLogResponseSchema.safeParse({
      items: [
        {
          entry_id: "00000000-0000-0000-0000-000000000001",
          organization_id: "org-1",
          version_number: 2,
          settings_snapshot: { llm_model: "gpt-4o-mini" },
          change_note: "Updated",
          changed_by_id: null,
          created_at: "2026-06-05T00:00:00Z",
        },
      ],
      total: 1,
    });
    expect(result.success).toBe(true);
  });

  it("accepts empty items list", () => {
    const result = modelProviderChangeLogResponseSchema.safeParse({
      items: [],
      total: 0,
    });
    expect(result.success).toBe(true);
  });
});
