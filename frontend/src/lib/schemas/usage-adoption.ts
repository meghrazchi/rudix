import { z } from "zod";

export const usageAdoptionSummarySchema = z.object({
  active_users: z.number().int(),
  new_users: z.number().int(),
  returning_users: z.number().int(),
  questions_asked: z.number().int(),
  documents_uploaded: z.number().int(),
  collections_used: z.number().int(),
  connectors_used: z.number().int(),
  citation_clicks: z.number().int(),
  trust_panel_opens: z.number().int(),
  feedback_submitted: z.number().int(),
  saved_answers: z.number().int(),
  onboarding_completion_rate: z.number().nullable(),
  invitations_sent: z.number().int(),
  invitations_accepted: z.number().int(),
  generated_at: z.string(),
});

export const activationFunnelStepSchema = z.object({
  step: z.string(),
  label: z.string(),
  users_reached: z.number().int(),
  drop_off_rate: z.number().nullable(),
});

export const activeUsersPointSchema = z.object({
  date: z.string(),
  active_users: z.number().int(),
});

export const questionsPerUserBucketSchema = z.object({
  bucket: z.string(),
  user_count: z.number().int(),
});

export const roleAdoptionRowSchema = z.object({
  role: z.string(),
  user_count: z.number().int(),
  active_users: z.number().int(),
  questions_asked: z.number().int(),
  activation_rate: z.number().nullable(),
});

export const usageAdoptionChartsSchema = z.object({
  active_users_series: z.array(activeUsersPointSchema),
  questions_per_user: z.array(questionsPerUserBucketSchema),
  feature_usage: z.record(z.string(), z.number().int()),
  funnel: z.array(activationFunnelStepSchema),
  role_adoption_comparison: z.array(roleAdoptionRowSchema),
  drop_off_points: z.array(activationFunnelStepSchema),
  generated_at: z.string(),
});

export const onboardingStatusSchema = z.enum([
  "not_started",
  "in_progress",
  "completed",
]);

export const usageAdoptionUserRowSchema = z.object({
  user_id: z.string(),
  name: z.string(),
  email: z.string(),
  role: z.string(),
  last_active_at: z.string().nullable().optional(),
  questions_asked: z.number().int(),
  sources_used: z.number().int(),
  citation_clicks: z.number().int(),
  feedback_submitted: z.number().int(),
  saved_answers: z.number().int(),
  onboarding_status: onboardingStatusSchema,
});

export const usageAdoptionUserListSchema = z.object({
  rows: z.array(usageAdoptionUserRowSchema),
  total: z.number().int(),
  page: z.number().int(),
  page_size: z.number().int(),
});

export const onboardingReminderResultSchema = z.object({
  sent: z.boolean(),
});

export type UsageAdoptionSummary = z.infer<typeof usageAdoptionSummarySchema>;
export type ActivationFunnelStep = z.infer<typeof activationFunnelStepSchema>;
export type UsageAdoptionCharts = z.infer<typeof usageAdoptionChartsSchema>;
export type OnboardingStatus = z.infer<typeof onboardingStatusSchema>;
export type UsageAdoptionUserRow = z.infer<typeof usageAdoptionUserRowSchema>;
export type UsageAdoptionUserList = z.infer<typeof usageAdoptionUserListSchema>;
export type OnboardingReminderResult = z.infer<
  typeof onboardingReminderResultSchema
>;

export type UsageAdoptionQuery = {
  from?: string;
  to?: string;
  role?: string;
  page?: number;
  page_size?: number;
};
