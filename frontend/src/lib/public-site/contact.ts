import { z } from "zod";

import { isExternalHref, type PublicSiteLinks } from "@/lib/public-site/links";

export const CONTACT_TEAM_SIZE_OPTIONS = [
  "1-10",
  "11-50",
  "51-250",
  "251-1000",
  "1000+",
] as const;

const TEAM_SIZE_OPTION_SET = new Set<string>(CONTACT_TEAM_SIZE_OPTIONS);

export const contactFormSchema = z
  .object({
    fullName: z
      .string()
      .trim()
      .min(2, "Full name must be at least 2 characters")
      .max(100, "Full name must be 100 characters or fewer"),
    workEmail: z
      .string()
      .trim()
      .min(1, "Work email is required")
      .email("Enter a valid work email address"),
    company: z
      .string()
      .trim()
      .min(2, "Company name must be at least 2 characters")
      .max(120, "Company name must be 120 characters or fewer"),
    roleTitle: z
      .string()
      .trim()
      .min(2, "Role or title must be at least 2 characters")
      .max(120, "Role or title must be 120 characters or fewer"),
    useCase: z
      .string()
      .trim()
      .min(2, "Use case must be at least 2 characters")
      .max(160, "Use case must be 160 characters or fewer"),
    teamSize: z.string().trim().min(1, "Team size is required"),
    message: z
      .string()
      .trim()
      .min(10, "Message must be at least 10 characters")
      .max(4000, "Message must be 4000 characters or fewer"),
    consentAccepted: z.boolean(),
    honeypot: z.string().trim().optional().default(""),
    captchaToken: z.string().trim().optional(),
  })
  .superRefine((value, context) => {
    if (!value.consentAccepted) {
      context.addIssue({
        code: z.ZodIssueCode.custom,
        path: ["consentAccepted"],
        message: "Consent is required before submitting the request.",
      });
    }
  });

export type ContactFormInputValues = z.input<typeof contactFormSchema>;
export type ContactFormValues = z.output<typeof contactFormSchema>;

export type ContactSubmissionMode =
  | "api"
  | "mailto"
  | "external"
  | "unavailable";

export type ContactSubmissionConfig = {
  mode: ContactSubmissionMode;
  apiEndpoint: string | null;
  mailtoAddress: string | null;
  externalSubmitUrl: string | null;
  schedulerUrl: string | null;
  captchaProvider: string | null;
  captchaSiteKey: string | null;
};

export type ContactSubmissionResult = {
  channel: "api" | "mailto" | "external";
  redirectTo: string | null;
  successMessage: string;
};

export type ContactSubmissionErrorKind =
  | "validation_failure"
  | "rate_limited"
  | "network_failure"
  | "not_configured"
  | "unknown";

export class ContactSubmissionError extends Error {
  readonly kind: ContactSubmissionErrorKind;
  readonly safeMessage: string;

  constructor(kind: ContactSubmissionErrorKind, safeMessage: string) {
    super(safeMessage);
    this.name = "ContactSubmissionError";
    this.kind = kind;
    this.safeMessage = safeMessage;
  }
}

function trimToNull(value: string | null | undefined): string | null {
  if (!value) {
    return null;
  }

  const trimmed = value.trim();
  return trimmed.length > 0 ? trimmed : null;
}

function resolveEnv(...keys: string[]): string | null {
  for (const key of keys) {
    const value = trimToNull(process.env[key]);
    if (value) {
      return value;
    }
  }

  return null;
}

function toMailtoHref(value: string): string {
  if (/^mailto:/i.test(value)) {
    return value;
  }

  if (value.includes("@")) {
    return `mailto:${value}`;
  }

  return value;
}

function createMailtoBody(values: ContactFormValues): string {
  const lines = [
    `Name: ${values.fullName}`,
    `Work Email: ${values.workEmail}`,
    `Company: ${values.company}`,
    `Role/Title: ${values.roleTitle}`,
    `Use Case: ${values.useCase}`,
    `Team Size: ${values.teamSize}`,
    "",
    "Message:",
    values.message,
  ];

  return lines.join("\n");
}

function inferExternalSubmitUrl(links: PublicSiteLinks): string | null {
  const configured = resolveEnv("NEXT_PUBLIC_CONTACT_SUBMIT_EXTERNAL_URL");
  if (configured) {
    return configured;
  }

  return isExternalHref(links.requestDemo) ? links.requestDemo : null;
}

function inferMailtoAddress(links: PublicSiteLinks): string | null {
  const configured = resolveEnv(
    "NEXT_PUBLIC_CONTACT_SUBMIT_MAILTO",
    "NEXT_PUBLIC_SUPPORT_EMAIL",
  );

  if (configured) {
    return toMailtoHref(configured);
  }

  return /^mailto:/i.test(links.contact) ? links.contact : null;
}

function resolveMode(
  config: Omit<ContactSubmissionConfig, "mode">,
): ContactSubmissionMode {
  if (config.apiEndpoint) {
    return "api";
  }

  if (config.mailtoAddress) {
    return "mailto";
  }

  if (config.externalSubmitUrl) {
    return "external";
  }

  return "unavailable";
}

function normalizeTeamSize(teamSize: string): string {
  return TEAM_SIZE_OPTION_SET.has(teamSize) ? teamSize : "custom";
}

function toSubmissionError(status: number | null): ContactSubmissionError {
  if (status === 400 || status === 422) {
    return new ContactSubmissionError(
      "validation_failure",
      "Some fields need attention. Review the form and try again.",
    );
  }

  if (status === 429) {
    return new ContactSubmissionError(
      "rate_limited",
      "Too many requests right now. Please wait a moment and retry.",
    );
  }

  if (status === 0 || status === 502 || status === 503 || status === 504) {
    return new ContactSubmissionError(
      "network_failure",
      "Submission is temporarily unavailable. Please retry or use email.",
    );
  }

  return new ContactSubmissionError(
    "unknown",
    "Unable to submit your request right now. Please try again.",
  );
}

export function resolveContactSubmissionConfig(
  links: PublicSiteLinks,
): ContactSubmissionConfig {
  const apiEndpoint = resolveEnv("NEXT_PUBLIC_CONTACT_SUBMIT_API_URL");
  const externalSubmitUrl = inferExternalSubmitUrl(links);
  const mailtoAddress = inferMailtoAddress(links);
  const schedulerUrl =
    resolveEnv("NEXT_PUBLIC_CONTACT_SCHEDULER_URL") ?? externalSubmitUrl;
  const captchaProvider = resolveEnv("NEXT_PUBLIC_CONTACT_CAPTCHA_PROVIDER");
  const captchaSiteKey = resolveEnv("NEXT_PUBLIC_CONTACT_CAPTCHA_SITE_KEY");

  const configWithoutMode = {
    apiEndpoint,
    mailtoAddress,
    externalSubmitUrl,
    schedulerUrl,
    captchaProvider,
    captchaSiteKey,
  };

  return {
    ...configWithoutMode,
    mode: resolveMode(configWithoutMode),
  };
}

export async function submitContactForm(
  values: ContactFormInputValues,
  config: ContactSubmissionConfig,
): Promise<ContactSubmissionResult> {
  const parsedValues = contactFormSchema.parse(values);

  if ((parsedValues.honeypot ?? "").trim().length > 0) {
    return {
      channel: "api",
      redirectTo: null,
      successMessage: "Thanks. Your request was received.",
    };
  }

  if (config.mode === "api" && config.apiEndpoint) {
    const payload = {
      full_name: parsedValues.fullName,
      work_email: parsedValues.workEmail,
      company: parsedValues.company,
      role_title: parsedValues.roleTitle,
      use_case: parsedValues.useCase,
      team_size: normalizeTeamSize(parsedValues.teamSize),
      message: parsedValues.message,
      consent_accepted: parsedValues.consentAccepted,
      captcha_token: trimToNull(parsedValues.captchaToken),
      source: "public_contact_page",
    };

    let response: Response;

    try {
      response = await fetch(config.apiEndpoint, {
        method: "POST",
        headers: {
          "content-type": "application/json",
        },
        body: JSON.stringify(payload),
      });
    } catch {
      throw toSubmissionError(0);
    }

    if (!response.ok) {
      throw toSubmissionError(response.status);
    }

    return {
      channel: "api",
      redirectTo: null,
      successMessage: "Thanks. We will contact you shortly.",
    };
  }

  if (config.mode === "mailto" && config.mailtoAddress) {
    const separator = config.mailtoAddress.includes("?") ? "&" : "?";
    const subject = encodeURIComponent("Rudix demo request");
    const body = encodeURIComponent(createMailtoBody(parsedValues));
    const redirectTo = `${config.mailtoAddress}${separator}subject=${subject}&body=${body}`;

    return {
      channel: "mailto",
      redirectTo,
      successMessage: "Opening your email client with a prefilled request.",
    };
  }

  if (config.mode === "external" && config.externalSubmitUrl) {
    return {
      channel: "external",
      redirectTo: config.externalSubmitUrl,
      successMessage: "Redirecting you to the configured scheduling flow.",
    };
  }

  throw new ContactSubmissionError(
    "not_configured",
    "Contact submission is not configured yet. Use the alternate contact options below.",
  );
}
