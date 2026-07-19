import type { ElementType, ReactNode } from "react";

type BidiTextProps = {
  children: ReactNode;
  as?: ElementType;
  className?: string;
};

/** Isolates user-authored text so it cannot reorder surrounding UI text. */
export function BidiText({
  children,
  as: Component = "bdi",
  className,
}: BidiTextProps) {
  return (
    <Component dir="auto" className={className}>
      {children}
    </Component>
  );
}

/** Keeps URLs, code, IDs, paths, emails, keys, dates, and numbers readable. */
export function TechnicalText({
  children,
  as: Component = "bdi",
  className,
}: BidiTextProps) {
  return (
    <Component dir="ltr" className={className}>
      {children}
    </Component>
  );
}
