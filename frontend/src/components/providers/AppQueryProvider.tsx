"use client";

import { QueryClientProvider } from "@tanstack/react-query";
import { useState } from "react";

import { createAppQueryClient } from "@/lib/api/query";

export function AppQueryProvider({ children }: { children: React.ReactNode }) {
  const [queryClient] = useState(() => createAppQueryClient());

  return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>;
}
