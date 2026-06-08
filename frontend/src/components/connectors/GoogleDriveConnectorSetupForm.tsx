"use client";

import { useState } from "react";

export type GoogleDriveConnectorConfig = {
  folder_ids: string[];
  drive_ids: string[];
  include_shared_drives: boolean;
};

type FieldError = {
  folder_ids?: string;
  drive_ids?: string;
};

function validate(config: GoogleDriveConnectorConfig): FieldError {
  const errors: FieldError = {};
  const badFolderIds = config.folder_ids.filter(
    (id) => id.includes(" ") || id.includes("/"),
  );
  if (badFolderIds.length > 0) {
    errors.folder_ids =
      "Folder IDs must not contain spaces or slashes. Paste the IDs from the Drive URL.";
  }
  if (config.include_shared_drives) {
    const badDriveIds = config.drive_ids.filter(
      (id) => id.includes(" ") || id.includes("/"),
    );
    if (badDriveIds.length > 0) {
      errors.drive_ids = "Shared Drive IDs must not contain spaces or slashes.";
    }
  }
  return errors;
}

function parseIds(raw: string): string[] {
  return raw
    .split(",")
    .map((id) => id.trim())
    .filter(Boolean);
}

type Props = {
  initialConfig?: Partial<GoogleDriveConnectorConfig>;
  onSubmit: (config: GoogleDriveConnectorConfig) => void;
  onCancel?: () => void;
  isSubmitting?: boolean;
  submitLabel?: string;
};

export function GoogleDriveConnectorSetupForm({
  initialConfig,
  onSubmit,
  onCancel,
  isSubmitting = false,
  submitLabel = "Connect Google Drive",
}: Props) {
  const [folderIdsRaw, setFolderIdsRaw] = useState(
    (initialConfig?.folder_ids ?? []).join(", "),
  );
  const [driveIdsRaw, setDriveIdsRaw] = useState(
    (initialConfig?.drive_ids ?? []).join(", "),
  );
  const [includeSharedDrives, setIncludeSharedDrives] = useState(
    initialConfig?.include_shared_drives ?? false,
  );
  const [errors, setErrors] = useState<FieldError>({});
  const [touched, setTouched] = useState<Record<string, boolean>>({});

  function buildConfig(): GoogleDriveConnectorConfig {
    return {
      folder_ids: parseIds(folderIdsRaw),
      drive_ids: includeSharedDrives ? parseIds(driveIdsRaw) : [],
      include_shared_drives: includeSharedDrives,
    };
  }

  function handleBlur(field: keyof FieldError) {
    setTouched((prev) => ({ ...prev, [field]: true }));
    setErrors(validate(buildConfig()));
  }

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    const config = buildConfig();
    const errs = validate(config);
    setErrors(errs);
    setTouched({ folder_ids: true, drive_ids: true });
    if (Object.keys(errs).length > 0) return;
    onSubmit(config);
  }

  const showError = (field: keyof FieldError) =>
    touched[field] && errors[field];

  return (
    <form onSubmit={handleSubmit} noValidate className="space-y-5">
      <div>
        <label
          htmlFor="gdrive-folder-ids"
          className="block text-sm font-medium text-gray-900"
        >
          Folder IDs{" "}
          <span className="font-normal text-gray-500">(optional)</span>
        </label>
        <p className="mt-0.5 text-xs text-gray-500">
          Comma-separated Google Drive folder IDs to sync recursively. Leave
          blank to sync all files in My Drive. Find the ID in the folder URL:{" "}
          <span className="font-mono">drive.google.com/drive/folders/</span>
          <span className="font-mono font-semibold">ID</span>
        </p>
        <input
          id="gdrive-folder-ids"
          type="text"
          placeholder="1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs, 0B4EYmsDV3..."
          value={folderIdsRaw}
          onChange={(e) => setFolderIdsRaw(e.target.value)}
          onBlur={() => handleBlur("folder_ids")}
          aria-describedby={
            showError("folder_ids") ? "gdrive-folder-ids-error" : undefined
          }
          aria-invalid={!!showError("folder_ids")}
          className={`mt-1.5 block w-full rounded-md border px-3 py-2 font-mono text-sm shadow-sm focus:ring-2 focus:outline-none ${
            showError("folder_ids")
              ? "border-red-400 focus:border-red-400 focus:ring-red-200"
              : "border-gray-300 focus:border-indigo-500 focus:ring-indigo-200"
          }`}
        />
        {showError("folder_ids") && (
          <p
            id="gdrive-folder-ids-error"
            role="alert"
            className="mt-1 text-xs text-red-600"
          >
            {errors.folder_ids}
          </p>
        )}
      </div>

      <div className="flex items-start gap-3">
        <input
          id="gdrive-include-shared-drives"
          type="checkbox"
          checked={includeSharedDrives}
          onChange={(e) => setIncludeSharedDrives(e.target.checked)}
          className="mt-0.5 h-4 w-4 rounded border-gray-300 text-indigo-600 focus:ring-indigo-500"
        />
        <div>
          <label
            htmlFor="gdrive-include-shared-drives"
            className="block text-sm font-medium text-gray-900"
          >
            Include Shared Drives
          </label>
          <p className="text-xs text-gray-500">
            Sync files from Shared Drives you have access to, in addition to My
            Drive.
          </p>
        </div>
      </div>

      {includeSharedDrives && (
        <div>
          <label
            htmlFor="gdrive-drive-ids"
            className="block text-sm font-medium text-gray-900"
          >
            Shared Drive IDs{" "}
            <span className="font-normal text-gray-500">(optional)</span>
          </label>
          <p className="mt-0.5 text-xs text-gray-500">
            Comma-separated Shared Drive IDs to limit sync. Leave blank to
            include all accessible Shared Drives.
          </p>
          <input
            id="gdrive-drive-ids"
            type="text"
            placeholder="0AF...abc, 0BG...xyz"
            value={driveIdsRaw}
            onChange={(e) => setDriveIdsRaw(e.target.value)}
            onBlur={() => handleBlur("drive_ids")}
            aria-describedby={
              showError("drive_ids") ? "gdrive-drive-ids-error" : undefined
            }
            aria-invalid={!!showError("drive_ids")}
            className={`mt-1.5 block w-full rounded-md border px-3 py-2 font-mono text-sm shadow-sm focus:ring-2 focus:outline-none ${
              showError("drive_ids")
                ? "border-red-400 focus:border-red-400 focus:ring-red-200"
                : "border-gray-300 focus:border-indigo-500 focus:ring-indigo-200"
            }`}
          />
          {showError("drive_ids") && (
            <p
              id="gdrive-drive-ids-error"
              role="alert"
              className="mt-1 text-xs text-red-600"
            >
              {errors.drive_ids}
            </p>
          )}
        </div>
      )}

      <div className="flex items-center justify-end gap-3 border-t border-gray-100 pt-4">
        {onCancel && (
          <button
            type="button"
            onClick={onCancel}
            disabled={isSubmitting}
            className="rounded-md border border-gray-300 px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50 disabled:opacity-50"
          >
            Cancel
          </button>
        )}
        <button
          type="submit"
          disabled={isSubmitting}
          className="rounded-md bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-700 disabled:opacity-50"
        >
          {isSubmitting ? "Connecting…" : submitLabel}
        </button>
      </div>
    </form>
  );
}
