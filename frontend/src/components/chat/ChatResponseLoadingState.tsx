"use client";

type ChatResponseLoadingStateProps = {
  label: string;
};

export function ChatResponseLoadingState({
  label,
}: ChatResponseLoadingStateProps) {
  return (
    <div className="flex flex-col items-start gap-3">
      <article className="rudix-thinking-gradient w-full min-w-0 rounded-3xl rounded-tl-none border border-transparent px-6 py-5 shadow-sm">
        <div className="mb-4 flex items-center gap-2">
          <span className="flex h-6 w-6 items-center justify-center rounded bg-[#3525cd] text-[10px] font-bold text-white italic">
            R
          </span>
          <p className="text-[10px] font-bold tracking-widest text-[#3525cd] uppercase">
            {label}
          </p>
          <span className="relative ml-auto flex h-2.5 w-2.5">
            <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-[#3525cd] opacity-30" />
            <span className="relative inline-flex h-2.5 w-2.5 rounded-full bg-[#3525cd]" />
          </span>
        </div>
        <div className="mt-3 space-y-2">
          <div className="rudix-skeleton-pulse h-3.5 w-3/4 rounded-full" />
          <div className="rudix-skeleton-pulse h-3.5 w-1/2 rounded-full" />
          <div className="rudix-skeleton-pulse h-3.5 w-5/6 rounded-full" />
        </div>
      </article>
    </div>
  );
}
