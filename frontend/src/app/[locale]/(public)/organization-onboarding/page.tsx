"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useEffect, useMemo, useState } from "react";
import { useFieldArray, useForm, useWatch } from "react-hook-form";
import Image from "next/image";
import Link from "next/link";
import { useRouter } from "next/navigation";

import {
  clearOnboardingDraft,
  completeOrganizationOnboarding,
  createDefaultOnboardingValues,
  loadOrganizationOnboardingDraft,
  organizationOnboardingSchema,
  parseDomainAllowlist,
  persistOrganizationOnboardingDraft,
  type OrganizationOnboardingError,
  type OrganizationOnboardingFormValues,
} from "@/lib/organization-onboarding";
import { trackActivationEvent } from "@/lib/analytics";
import { useAuthSession } from "@/lib/use-auth-session";

const stepLabels = ["Workspace", "Access", "Invites", "Review"] as const;
const stepFieldNames: Array<Array<keyof OrganizationOnboardingFormValues>> = [
  ["workspaceName"],
  ["domainAllowlistText", "defaultAccessRole", "allowSelfServeJoin"],
  ["invites"],
  [],
];

function safeErrorMessage(error: unknown): string {
  if (typeof error === "object" && error !== null && "safeMessage" in error) {
    const candidate = error as Partial<OrganizationOnboardingError> & {
      safeMessage?: unknown;
    };
    if (
      typeof candidate.safeMessage === "string" &&
      candidate.safeMessage.trim()
    ) {
      return candidate.safeMessage;
    }
  }

  return "Unable to complete organization onboarding. Please try again.";
}

export default function OrganizationOnboardingPage() {
  const router = useRouter();
  const { state, setAuthenticatedSession } = useAuthSession();

  const [currentStep, setCurrentStep] = useState(0);
  const [loadingDraft, setLoadingDraft] = useState(true);
  const [submissionError, setSubmissionError] = useState<string | null>(null);
  const [saveMessage, setSaveMessage] = useState<string | null>(null);

  const form = useForm<OrganizationOnboardingFormValues>({
    resolver: zodResolver(organizationOnboardingSchema),
    defaultValues: createDefaultOnboardingValues(),
    mode: "onSubmit",
  });

  const invitesArray = useFieldArray({
    control: form.control,
    name: "invites",
  });

  const watchedInvites = useWatch({
    control: form.control,
    name: "invites",
  });

  const watchedWorkspaceName = useWatch({
    control: form.control,
    name: "workspaceName",
  });

  const watchedDomainAllowlistText = useWatch({
    control: form.control,
    name: "domainAllowlistText",
  });

  const reviewInvites = useMemo(
    () =>
      (watchedInvites ?? [])
        .map((invite) => ({
          email: invite.email.trim().toLowerCase(),
          role: invite.role,
        }))
        .filter((invite) => invite.email.length > 0),
    [watchedInvites],
  );

  const reviewDomains = useMemo(
    () => parseDomainAllowlist(watchedDomainAllowlistText ?? ""),
    [watchedDomainAllowlistText],
  );

  useEffect(() => {
    if (state.status === "unauthenticated") {
      router.replace("/login?next=%2Forganization-onboarding");
      return;
    }

    if (state.status === "authenticated" && state.session?.organizationId) {
      router.replace("/dashboard");
      return;
    }
  }, [router, state]);

  useEffect(() => {
    let isMounted = true;

    async function hydrateDraft() {
      try {
        const draft = await loadOrganizationOnboardingDraft();
        if (!isMounted || !draft) {
          return;
        }

        const nextValues = {
          ...createDefaultOnboardingValues(),
          ...draft,
        };

        if (!nextValues.invites.length) {
          nextValues.invites = [{ email: "", role: "member" }];
        }

        form.reset(nextValues);
      } catch (error) {
        if (!isMounted) {
          return;
        }
        setSubmissionError(safeErrorMessage(error));
      } finally {
        if (isMounted) {
          setLoadingDraft(false);
        }
      }
    }

    void hydrateDraft();

    return () => {
      isMounted = false;
    };
  }, [form]);

  async function handleSaveDraft() {
    setSubmissionError(null);
    setSaveMessage(null);

    try {
      await persistOrganizationOnboardingDraft(form.getValues());
      setSaveMessage("Draft saved. You can resume onboarding later.");
    } catch (error) {
      setSubmissionError(safeErrorMessage(error));
    }
  }

  async function handleComplete(values: OrganizationOnboardingFormValues) {
    setSubmissionError(null);
    setSaveMessage(null);

    try {
      const result = await completeOrganizationOnboarding(values);
      void trackActivationEvent("activation.organization_created", {
        surface: "public",
        route: "/organization-onboarding",
        pageKey: "organization-onboarding",
        featureArea: "settings",
        source: values.defaultAccessRole,
      });
      if (!state.session) {
        router.replace("/dashboard");
        return;
      }

      setAuthenticatedSession({
        ...state.session,
        organizationId: result.organizationId,
        organizationName: result.organizationName,
        role: result.role,
      });
      router.replace("/dashboard");
    } catch (error) {
      setSubmissionError(safeErrorMessage(error));
    }
  }

  async function goToNextStep() {
    const fieldsToValidate = stepFieldNames[currentStep];

    if (fieldsToValidate.length > 0) {
      const valid = await form.trigger(fieldsToValidate);
      if (!valid) {
        return;
      }
    }

    setCurrentStep((step) => Math.min(step + 1, stepLabels.length - 1));
  }

  function goToPreviousStep() {
    setCurrentStep((step) => Math.max(step - 1, 0));
  }

  if (state.status !== "authenticated" || loadingDraft) {
    return (
      <div
        data-public-theme="system"
        className="rudix-public bg-site-canvas text-site-ink flex min-h-screen items-center justify-center bg-[radial-gradient(60%_45%_at_50%_0%,var(--site-accent-soft),transparent)] px-6"
      >
        <div className="border-site-border bg-site-surface w-full max-w-xl rounded-2xl border p-7 text-center shadow-sm">
          <h1 className="text-site-ink text-2xl font-bold">
            Preparing organization setup
          </h1>
          <p className="text-site-ink-muted mt-2 text-sm">
            Loading your onboarding state.
          </p>
        </div>
      </div>
    );
  }

  return (
    <div
      data-public-theme="system"
      className="rudix-public bg-site-canvas text-site-ink flex min-h-screen items-center justify-center bg-[radial-gradient(60%_45%_at_50%_0%,var(--site-accent-soft),transparent)] px-6 py-8"
    >
      <main className="border-site-border bg-site-surface w-full max-w-3xl rounded-3xl border p-7 shadow-[0_24px_60px_-32px_rgba(15,17,23,0.25)] md:p-9">
        <div className="mb-2 flex items-center gap-2">
          <Image
            src="/brand/rudix-mark.svg"
            alt="Rudix logo"
            width={18}
            height={18}
            className="h-[18px] w-[18px]"
          />
          <p className="text-site-ink-muted text-xs font-bold tracking-[0.18em] uppercase">
            Rudix Setup
          </p>
        </div>
        <h1 className="text-site-ink mb-2 text-3xl font-semibold tracking-tight">
          Organization onboarding
        </h1>
        <p className="text-site-ink-muted mb-5 text-sm">
          Create your workspace, configure access defaults, and invite initial
          team members.
        </p>

        <ol className="mb-6 grid gap-2 sm:grid-cols-4">
          {stepLabels.map((label, index) => (
            <li
              key={label}
              className={`rounded-lg border px-3 py-2 text-xs font-semibold tracking-wide uppercase ${
                index <= currentStep
                  ? "border-site-accent bg-site-canvas text-site-accent-ink"
                  : "border-site-border bg-site-surface text-site-ink-subtle"
              }`}
            >
              Step {index + 1}: {label}
            </li>
          ))}
        </ol>

        <form
          className="space-y-5"
          onSubmit={form.handleSubmit(handleComplete)}
          noValidate
        >
          {currentStep === 0 ? (
            <section className="space-y-3">
              <label className="block" htmlFor="workspaceName">
                <span className="text-site-ink-muted mb-1 block text-xs font-medium">
                  Workspace name
                </span>
                <input
                  id="workspaceName"
                  type="text"
                  autoComplete="organization"
                  {...form.register("workspaceName")}
                  className="border-site-border ring-site-accent/20 h-10 w-full rounded-lg border px-3 text-sm outline-none focus:ring"
                />
              </label>
              {form.formState.errors.workspaceName?.message ? (
                <p
                  role="alert"
                  className="text-xs text-rose-700 dark:text-rose-300"
                >
                  {form.formState.errors.workspaceName.message}
                </p>
              ) : null}
            </section>
          ) : null}

          {currentStep === 1 ? (
            <section className="space-y-3">
              <label className="block" htmlFor="domainAllowlistText">
                <span className="text-site-ink-muted mb-1 block text-xs font-medium">
                  Domain allowlist (optional)
                </span>
                <textarea
                  id="domainAllowlistText"
                  rows={4}
                  placeholder="example.com\nacme.org"
                  {...form.register("domainAllowlistText")}
                  className="border-site-border ring-site-accent/20 w-full rounded-lg border px-3 py-2 text-sm outline-none focus:ring"
                />
              </label>
              {form.formState.errors.domainAllowlistText?.message ? (
                <p
                  role="alert"
                  className="text-xs text-rose-700 dark:text-rose-300"
                >
                  {form.formState.errors.domainAllowlistText.message}
                </p>
              ) : null}

              <label className="block" htmlFor="defaultAccessRole">
                <span className="text-site-ink-muted mb-1 block text-xs font-medium">
                  Default access role
                </span>
                <select
                  id="defaultAccessRole"
                  {...form.register("defaultAccessRole")}
                  className="border-site-border bg-site-surface ring-site-accent/20 h-10 w-full rounded-lg border px-3 text-sm outline-none focus:ring"
                >
                  <option value="member">member</option>
                  <option value="viewer">viewer</option>
                </select>
              </label>

              <label className="border-site-border bg-site-surface text-site-ink flex items-start gap-2 rounded-lg border p-3 text-sm">
                <input
                  type="checkbox"
                  {...form.register("allowSelfServeJoin")}
                  className="mt-0.5"
                />
                <span>
                  Allow users with approved domains to self-join this workspace
                </span>
              </label>
            </section>
          ) : null}

          {currentStep === 2 ? (
            <section className="space-y-3">
              <div className="flex items-center justify-between">
                <p className="text-site-ink-muted text-xs font-medium">
                  Initial invites
                </p>
                <button
                  type="button"
                  onClick={() =>
                    invitesArray.append({ email: "", role: "member" })
                  }
                  className="border-site-border text-site-accent-ink hover:bg-site-canvas rounded-lg border px-3 py-1 text-xs font-semibold"
                >
                  Add invite
                </button>
              </div>

              <div className="space-y-2">
                {invitesArray.fields.map((field, index) => (
                  <div
                    key={field.id}
                    className="grid gap-2 sm:grid-cols-[1fr_150px_auto]"
                  >
                    <input
                      type="email"
                      placeholder="teammate@company.com"
                      {...form.register(`invites.${index}.email` as const)}
                      className="border-site-border ring-site-accent/20 h-10 rounded-lg border px-3 text-sm outline-none focus:ring"
                    />
                    <select
                      {...form.register(`invites.${index}.role` as const)}
                      className="border-site-border bg-site-surface ring-site-accent/20 h-10 rounded-lg border px-3 text-sm outline-none focus:ring"
                    >
                      <option value="admin">admin</option>
                      <option value="member">member</option>
                      <option value="viewer">viewer</option>
                    </select>
                    <button
                      type="button"
                      onClick={() => invitesArray.remove(index)}
                      disabled={invitesArray.fields.length <= 1}
                      className="border-site-border text-site-ink-subtle hover:bg-site-canvas h-10 rounded-lg border px-3 text-xs font-semibold disabled:opacity-50"
                    >
                      Remove
                    </button>
                    {form.formState.errors.invites?.[index]?.email?.message ? (
                      <p
                        role="alert"
                        className="text-xs text-rose-700 sm:col-span-3 dark:text-rose-300"
                      >
                        {form.formState.errors.invites[index]?.email?.message}
                      </p>
                    ) : null}
                  </div>
                ))}
              </div>
            </section>
          ) : null}

          {currentStep === 3 ? (
            <section className="space-y-4">
              <div className="border-site-border bg-site-surface rounded-lg border p-4">
                <p className="text-site-ink-muted mb-2 text-xs font-medium">
                  Workspace
                </p>
                <p className="text-site-ink text-sm">
                  {watchedWorkspaceName || "-"}
                </p>
              </div>

              <div className="border-site-border bg-site-surface rounded-lg border p-4">
                <p className="text-site-ink-muted mb-2 text-xs font-medium">
                  Allowed domains
                </p>
                {reviewDomains.length ? (
                  <ul className="text-site-ink list-disc pl-5 text-sm">
                    {reviewDomains.map((domain) => (
                      <li key={domain}>{domain}</li>
                    ))}
                  </ul>
                ) : (
                  <p className="text-site-ink-muted text-sm">
                    No domain restrictions configured.
                  </p>
                )}
              </div>

              <div className="border-site-border bg-site-surface rounded-lg border p-4">
                <p className="text-site-ink-muted mb-2 text-xs font-medium">
                  Invites
                </p>
                {reviewInvites.length ? (
                  <ul className="text-site-ink space-y-1 text-sm">
                    {reviewInvites.map((invite) => (
                      <li key={`${invite.email}:${invite.role}`}>
                        {invite.email} ({invite.role})
                      </li>
                    ))}
                  </ul>
                ) : (
                  <p className="text-site-ink-muted text-sm">
                    No initial invites added.
                  </p>
                )}
              </div>
            </section>
          ) : null}

          {saveMessage ? (
            <p className="rounded-lg border border-emerald-200 bg-emerald-50 px-3 py-2 text-sm text-emerald-700 dark:border-emerald-900/60 dark:bg-emerald-950/40 dark:text-emerald-300">
              {saveMessage}
            </p>
          ) : null}

          {submissionError ? (
            <p
              role="alert"
              className="rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-700 dark:border-rose-900/60 dark:bg-rose-950/40 dark:text-rose-300"
            >
              {submissionError}
            </p>
          ) : null}

          <div className="flex flex-wrap items-center justify-between gap-2">
            <div className="flex gap-2">
              <button
                type="button"
                onClick={goToPreviousStep}
                disabled={currentStep === 0}
                className="border-site-border text-site-accent-ink hover:bg-site-canvas rounded-lg border px-4 py-2 text-sm font-semibold disabled:opacity-50"
              >
                Back
              </button>
              {currentStep < stepLabels.length - 1 ? (
                <button
                  type="button"
                  onClick={() => {
                    void goToNextStep();
                  }}
                  className="bg-site-accent text-site-on-accent hover:bg-site-accent-hover rounded-full px-4 py-2 text-sm font-semibold"
                >
                  Next
                </button>
              ) : (
                <button
                  type="submit"
                  disabled={form.formState.isSubmitting}
                  className="bg-site-accent text-site-on-accent hover:bg-site-accent-hover rounded-full px-4 py-2 text-sm font-semibold disabled:opacity-60"
                >
                  {form.formState.isSubmitting
                    ? "Finishing..."
                    : "Complete setup"}
                </button>
              )}
            </div>

            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={() => {
                  clearOnboardingDraft();
                  form.reset(createDefaultOnboardingValues());
                  setCurrentStep(0);
                  setSaveMessage("Draft cleared.");
                }}
                className="border-site-border text-site-ink-subtle hover:bg-site-canvas rounded-lg border px-4 py-2 text-sm font-semibold"
              >
                Reset
              </button>
              <button
                type="button"
                onClick={() => {
                  void handleSaveDraft();
                }}
                className="border-site-border text-site-accent-ink hover:bg-site-canvas rounded-lg border px-4 py-2 text-sm font-semibold"
              >
                Save draft
              </button>
              <Link
                href="/dashboard"
                className="text-site-ink-muted decoration-site-ink-subtle text-sm font-semibold underline"
              >
                Skip to dashboard
              </Link>
            </div>
          </div>
        </form>
      </main>
    </div>
  );
}
