"use client";

import { QueryClientProvider } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import { createAppQueryClient, registerAppQueryClient } from "@/lib/api/query";

export function AppQueryProvider({ children }: { children: React.ReactNode }) {
  const [queryClient] = useState(() => createAppQueryClient());

  useEffect(() => registerAppQueryClient(queryClient), [queryClient]);

  return (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );
}
