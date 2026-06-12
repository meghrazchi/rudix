"use client";

import { useQuery } from "@tanstack/react-query";

import {
  getPublicFeatureFlags,
  type FeatureFlagName,
  type PublicFeatureFlagsResponse,
} from "@/lib/api/feature-flags";
import { queryKeys } from "@/lib/api/query";

export type UseFeatureFlagsResult = {
  flags: Record<string, boolean>;
  isLoading: boolean;
  isError: boolean;
  isEnabled: (flag: FeatureFlagName) => boolean;
};

export function useFeatureFlags(): UseFeatureFlagsResult {
  const { data, isLoading, isError } = useQuery<PublicFeatureFlagsResponse>({
    queryKey: queryKeys.featureFlags,
    queryFn: getPublicFeatureFlags,
  });

  const flags = data?.flags ?? {};

  return {
    flags,
    isLoading,
    isError,
    isEnabled: (flag: FeatureFlagName) => Boolean(flags[flag]),
  };
}
