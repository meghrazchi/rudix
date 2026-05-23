const REDACTED_VALUE = "[REDACTED]";
const TRUNCATED_VALUE = "[TRUNCATED]";
const CIRCULAR_VALUE = "[CIRCULAR]";
const MAX_DEPTH = 4;
const MAX_KEYS = 40;
const MAX_ARRAY_ITEMS = 25;
const MAX_STRING_LENGTH = 240;

const SENSITIVE_KEY_PATTERN =
  /(token|secret|password|authorization|cookie|api[_-]?key|document[_-]?text|raw[_-]?text|prompt|question|answer|content|snippet|input|output|access[_-]?token|refresh[_-]?token)/i;

function clampString(value: string): string {
  if (value.length <= MAX_STRING_LENGTH) {
    return value;
  }
  return `${value.slice(0, MAX_STRING_LENGTH)}…`;
}

function isPrimitive(
  value: unknown,
): value is string | number | boolean | null {
  return (
    typeof value === "string" ||
    typeof value === "number" ||
    typeof value === "boolean" ||
    value === null
  );
}

function redactKeyValue(
  key: string,
  value: unknown,
  depth: number,
  seen: WeakSet<object>,
): unknown {
  if (SENSITIVE_KEY_PATTERN.test(key)) {
    return REDACTED_VALUE;
  }
  return redactObservabilityValue(value, depth + 1, seen);
}

export function redactObservabilityValue(
  value: unknown,
  depth = 0,
  seen = new WeakSet<object>(),
): unknown {
  if (depth > MAX_DEPTH) {
    return TRUNCATED_VALUE;
  }

  if (isPrimitive(value)) {
    if (typeof value === "string") {
      return clampString(value);
    }
    return value;
  }

  if (typeof value === "bigint") {
    return value.toString();
  }

  if (typeof value === "function") {
    return "[Function]";
  }

  if (value instanceof Date) {
    return value.toISOString();
  }

  if (Array.isArray(value)) {
    const trimmed = value.slice(0, MAX_ARRAY_ITEMS);
    const redacted = trimmed.map((item) =>
      redactObservabilityValue(item, depth + 1, seen),
    );
    if (value.length > MAX_ARRAY_ITEMS) {
      redacted.push(`[+${value.length - MAX_ARRAY_ITEMS} items]`);
    }
    return redacted;
  }

  if (typeof value === "object" && value !== null) {
    if (seen.has(value)) {
      return CIRCULAR_VALUE;
    }
    seen.add(value);

    const entries = Object.entries(value).slice(0, MAX_KEYS);
    const result: Record<string, unknown> = {};

    for (const [key, entryValue] of entries) {
      result[key] = redactKeyValue(key, entryValue, depth, seen);
    }

    if (Object.keys(value).length > MAX_KEYS) {
      result.__truncated__ = true;
    }

    return result;
  }

  return String(value);
}

export function redactObservabilityRecord(
  value: Record<string, unknown> | null | undefined,
): Record<string, unknown> {
  if (!value) {
    return {};
  }
  const redacted = redactObservabilityValue(value);
  if (
    typeof redacted === "object" &&
    redacted !== null &&
    !Array.isArray(redacted)
  ) {
    return redacted as Record<string, unknown>;
  }
  return {};
}

export const observabilityRedactionConstants = {
  REDACTED_VALUE,
  TRUNCATED_VALUE,
  CIRCULAR_VALUE,
};
