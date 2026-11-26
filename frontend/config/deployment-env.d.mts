export function resolveDeploymentEnvironment(
  env: Record<string, string | undefined>,
): string | null;
export function isProductionLikeEnvironment(
  env: Record<string, string | undefined>,
): boolean;
