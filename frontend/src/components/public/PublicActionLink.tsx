import { Link } from "@/i18n/navigation";
import { forwardRef } from "react";

import { isExternalHref } from "@/lib/public-site/links";

export const PUBLIC_FOCUS_RING_CLASS =
  "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#3a35e8] focus-visible:ring-offset-2 focus-visible:ring-offset-transparent";

type PublicActionLinkProps = {
  href: string;
  className?: string;
  children: React.ReactNode;
  ariaLabel?: string;
  onClick?: () => void;
};

export const PublicActionLink = forwardRef<
  HTMLAnchorElement,
  PublicActionLinkProps
>(({ href, className, children, ariaLabel, onClick }, ref) => {
  const mergedClassName =
    `${className ?? ""} ${PUBLIC_FOCUS_RING_CLASS}`.trim();

  if (isExternalHref(href)) {
    return (
      <a
        href={href}
        target="_blank"
        rel="noreferrer noopener"
        aria-label={ariaLabel}
        className={mergedClassName}
        onClick={onClick}
        ref={ref}
      >
        {children}
      </a>
    );
  }

  return (
    <Link
      href={href}
      aria-label={ariaLabel}
      className={mergedClassName}
      onClick={onClick}
      ref={ref}
    >
      {children}
    </Link>
  );
});

PublicActionLink.displayName = "PublicActionLink";
