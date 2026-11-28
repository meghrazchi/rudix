"use client";

import { lazy, Suspense, useState, type ComponentProps } from "react";

import { SkeletonBlock } from "@/components/states/SkeletonBlock";
import type { AssignCollectionsDialog as AssignCollectionsDialogContent } from "@/components/collections/AssignCollectionsDialog";
import type { DeleteConfirmModal as DeleteConfirmModalContent } from "@/components/documents/DeleteConfirmModal";
import type { DocumentsUploadModal as DocumentsUploadModalContent } from "@/components/documents/DocumentsUploadModal";

// The documents page dialogs load on first open (R07-03). React.lazy rather
// than next/dynamic keeps the next/dynamic loader off this route.
const UploadModalLazy = lazy(() =>
  import("@/components/documents/DocumentsUploadModal").then((module) => ({
    default: module.DocumentsUploadModal,
  })),
);
const DeleteModalLazy = lazy(() =>
  import("@/components/documents/DeleteConfirmModal").then((module) => ({
    default: module.DeleteConfirmModal,
  })),
);
const AssignDialogLazy = lazy(() =>
  import("@/components/collections/AssignCollectionsDialog").then((module) => ({
    default: module.AssignCollectionsDialog,
  })),
);

/** Backdrop and card shown for the moment a dialog module is loading. */
function DialogLoading() {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-[#17172a]/40 px-4">
      <div className="w-full max-w-md rounded-xl bg-white p-6 shadow-xl ring-1 ring-[#e5e3f1]">
        <SkeletonBlock rows={4} />
      </div>
    </div>
  );
}

/** True from the first render with `open` set; stays true afterwards. */
function useOpenedOnce(open: boolean): boolean {
  const [opened, setOpened] = useState(open);
  if (open && !opened) {
    setOpened(true);
  }
  return opened || open;
}

/**
 * Mounted from its first open on and kept mounted, as before, so the
 * metadata fields keep their values between opens.
 */
export function DocumentsUploadModal(
  props: ComponentProps<typeof DocumentsUploadModalContent>,
) {
  const opened = useOpenedOnce(props.isOpen);
  if (!opened) {
    return null;
  }
  return (
    <Suspense fallback={props.isOpen ? <DialogLoading /> : null}>
      <UploadModalLazy {...props} />
    </Suspense>
  );
}

export function DeleteConfirmModal(
  props: ComponentProps<typeof DeleteConfirmModalContent>,
) {
  const opened = useOpenedOnce(props.open);
  if (!opened) {
    return null;
  }
  return (
    <Suspense fallback={props.open ? <DialogLoading /> : null}>
      <DeleteModalLazy {...props} />
    </Suspense>
  );
}

/** Rendered only while a document is being assigned, as before. */
export function AssignCollectionsDialog(
  props: ComponentProps<typeof AssignCollectionsDialogContent>,
) {
  return (
    <Suspense fallback={<DialogLoading />}>
      <AssignDialogLazy {...props} />
    </Suspense>
  );
}
