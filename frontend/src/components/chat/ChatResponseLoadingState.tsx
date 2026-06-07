"use client";

type ChatResponseLoadingStateProps = {
  label: string;
};

export function ChatResponseLoadingState({
  label,
}: ChatResponseLoadingStateProps) {
  return (
    <div className="flex items-start gap-3">
      <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-[#3525cd] text-white">
        <span
          className="material-symbols-outlined text-[18px]"
          aria-hidden="true"
          style={{ fontVariationSettings: "'FILL' 1" }}
        >
          bolt
        </span>
      </div>
      <article className="min-w-0 rounded-xl rounded-tl-none border border-[#c7c4d8] bg-white px-4 py-3 shadow-sm">
        <div className="flex items-center gap-2">
          <span className="relative flex h-2.5 w-2.5">
            <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-[#3525cd] opacity-30" />
            <span className="relative inline-flex h-2.5 w-2.5 rounded-full bg-[#3525cd]" />
          </span>
          <p className="text-sm font-medium text-[#464555]">{label}</p>
        </div>
        <div className="mt-3 space-y-2">
          <div className="h-2.5 w-[18rem] max-w-full animate-pulse rounded-full bg-[#ece8ff]" />
          <div className="h-2.5 w-[14rem] max-w-[85%] animate-pulse rounded-full bg-[#ece8ff]" />
          <div className="h-2.5 w-[10rem] max-w-[70%] animate-pulse rounded-full bg-[#ece8ff]" />
        </div>
      </article>
    </div>
  );
}
