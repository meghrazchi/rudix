import { PublicActionLink } from "@/components/public/PublicActionLink";

type PublicCtaProps = {
  href: string;
  label: string;
  variant?: "primary" | "secondary" | "outline";
  className?: string;
};

const variantClassNames: Record<
  NonNullable<PublicCtaProps["variant"]>,
  string
> = {
  primary:
    "rounded-md bg-[#3a35e8] px-5 py-3 text-sm font-semibold text-white shadow-[0_6px_20px_rgba(58,53,232,0.35)] transition hover:bg-[#2d2ad1]",
  secondary:
    "rounded-md border border-[#c7cad6] bg-white px-5 py-3 text-sm font-semibold text-[#2a2f40] transition hover:bg-[#f6f7fb]",
  outline:
    "rounded-md border border-white/75 px-5 py-3 text-sm font-semibold text-white transition hover:bg-white/10",
};

export function PublicCta({
  href,
  label,
  variant = "primary",
  className,
}: PublicCtaProps) {
  const classes = [variantClassNames[variant], className]
    .filter(Boolean)
    .join(" ");
  return (
    <PublicActionLink href={href} className={classes}>
      {label}
    </PublicActionLink>
  );
}
