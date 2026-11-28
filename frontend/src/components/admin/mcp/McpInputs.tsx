"use client";

import { useState } from "react";

export function TagListEditor({
  label,
  description,
  value,
  onChange,
  placeholder,
}: {
  label: string;
  description: string;
  value: string[] | null;
  onChange: (v: string[] | null) => void;
  placeholder?: string;
}) {
  const [useDefault, setUseDefault] = useState(value === null);
  const [tags, setTags] = useState<string[]>(value ?? []);
  const [input, setInput] = useState("");

  function toggleDefault(toDefault: boolean) {
    setUseDefault(toDefault);
    onChange(toDefault ? null : tags);
  }

  function addTag() {
    const trimmed = input.trim().toLowerCase();
    if (!trimmed || tags.includes(trimmed)) return;
    const next = [...tags, trimmed];
    setTags(next);
    onChange(next);
    setInput("");
  }

  function removeTag(tag: string) {
    const next = tags.filter((t) => t !== tag);
    setTags(next);
    onChange(next);
  }

  return (
    <div>
      <div className="mb-1 flex items-center justify-between">
        <div>
          <p className="text-sm font-medium text-[#2a2640]">{label}</p>
          <p className="text-xs text-[#68647b]">{description}</p>
        </div>
        <label className="flex cursor-pointer items-center gap-1.5 text-xs text-[#68647b]">
          <input
            type="checkbox"
            className="h-3.5 w-3.5 accent-[#3525cd]"
            checked={useDefault}
            onChange={(e) => toggleDefault(e.target.checked)}
          />
          Allow all (no restriction)
        </label>
      </div>
      {!useDefault && (
        <div className="rounded-lg border border-[#d7d4e8] p-3">
          <div className="mb-2 flex flex-wrap gap-1">
            {tags.map((tag) => (
              <span
                key={tag}
                className="flex items-center gap-1 rounded-full bg-[#f5f3ff] px-2.5 py-0.5 text-xs text-[#4d4880]"
              >
                {tag}
                <button
                  type="button"
                  onClick={() => removeTag(tag)}
                  className="ml-0.5 text-[#68647b] hover:text-red-600"
                  aria-label={`Remove ${tag}`}
                >
                  ×
                </button>
              </span>
            ))}
            {tags.length === 0 && (
              <span className="text-xs text-[#68647b]">
                Empty — nothing is allowed for this field.
              </span>
            )}
          </div>
          <div className="flex gap-2">
            <input
              type="text"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) =>
                e.key === "Enter" && (e.preventDefault(), addTag())
              }
              placeholder={placeholder ?? "Enter value and press Enter"}
              className="flex-1 rounded border border-[#d7d4e8] px-2 py-1 text-xs focus:border-[#3525cd] focus:outline-none"
            />
            <button
              type="button"
              onClick={addTag}
              className="rounded bg-[#f5f3ff] px-3 py-1 text-xs font-medium text-[#3525cd] hover:bg-[#ebe8ff]"
            >
              Add
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

export function NullableNumberInput({
  label,
  description,
  value,
  onChange,
  min,
  unit,
}: {
  label: string;
  description: string;
  value: number | null;
  onChange: (v: number | null) => void;
  min: number;
  unit?: string;
}) {
  const hasLimit = value !== null;
  return (
    <div>
      <div className="mb-1 flex items-center justify-between">
        <div>
          <p className="text-sm font-medium text-[#2a2640]">{label}</p>
          <p className="text-xs text-[#68647b]">{description}</p>
        </div>
        <label className="flex cursor-pointer items-center gap-1.5 text-xs text-[#68647b]">
          <input
            type="checkbox"
            className="h-3.5 w-3.5 accent-[#3525cd]"
            checked={!hasLimit}
            onChange={(e) => onChange(e.target.checked ? null : min)}
          />
          No limit
        </label>
      </div>
      {hasLimit && (
        <div className="flex items-center gap-2">
          <input
            type="number"
            min={min}
            value={value}
            onChange={(e) => onChange(Number(e.target.value))}
            className="w-40 rounded-lg border border-[#d7d4e8] px-3 py-2 text-sm focus:border-[#3525cd] focus:outline-none"
          />
          {unit && <span className="text-xs text-[#68647b]">{unit}</span>}
        </div>
      )}
    </div>
  );
}
