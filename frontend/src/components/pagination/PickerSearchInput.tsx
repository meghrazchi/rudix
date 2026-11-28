"use client";

type PickerSearchInputProps = {
  value: string;
  onChange: (value: string) => void;
  placeholder: string;
  ariaLabel: string;
  disabled?: boolean;
  className?: string;
};

/** Compact search box for server-searched pickers. */
export function PickerSearchInput({
  value,
  onChange,
  placeholder,
  ariaLabel,
  disabled = false,
  className,
}: PickerSearchInputProps) {
  return (
    <div className={`relative ${className ?? ""}`}>
      <span
        aria-hidden="true"
        className="material-symbols-outlined pointer-events-none absolute top-1/2 left-2 -translate-y-1/2 text-base text-[#9993b8]"
      >
        search
      </span>
      <input
        type="search"
        value={value}
        disabled={disabled}
        aria-label={ariaLabel}
        placeholder={placeholder}
        onChange={(event) => onChange(event.target.value)}
        className="h-9 w-full rounded-lg border border-[#d2cee6] bg-white pr-3 pl-8 text-sm text-[#2a2640] outline-none placeholder:text-[#b0abc8] focus:ring-2 focus:ring-[#3525cd]/20 disabled:opacity-60"
      />
    </div>
  );
}
