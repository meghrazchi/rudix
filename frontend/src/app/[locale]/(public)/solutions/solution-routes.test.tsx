import { render, screen } from "@testing-library/react";
import type { Metadata } from "next";
import type { ComponentType } from "react";
import { describe, expect, it } from "vitest";

import ClientPortalRoute, {
  generateMetadata as clientPortalMetadata,
} from "./client-portal/page";
import ComplianceRoute, {
  generateMetadata as complianceMetadata,
} from "./compliance/page";
import HRRoute, { generateMetadata as hrMetadata } from "./hr/page";
import InternalKnowledgeRoute, {
  generateMetadata as internalKnowledgeMetadata,
} from "./internal-knowledge/page";
import LegalRoute, { generateMetadata as legalMetadata } from "./legal/page";
import OperationsRoute, {
  generateMetadata as operationsMetadata,
} from "./operations/page";
import ProcurementRoute, {
  generateMetadata as procurementMetadata,
} from "./procurement/page";
import ResearchRoute, {
  generateMetadata as researchMetadata,
} from "./research/page";
import SalesRoute, { generateMetadata as salesMetadata } from "./sales/page";
import SupportRoute, {
  generateMetadata as supportMetadata,
} from "./support/page";

type MetadataLoader = (input: {
  params: Promise<{ locale: string }>;
}) => Promise<Metadata>;

type SolutionRoute = {
  path: string;
  label: string;
  Route: ComponentType;
  metadata: MetadataLoader;
};

const ROUTES: SolutionRoute[] = [
  {
    path: "/solutions/client-portal",
    label: "Client Portal solution page",
    Route: ClientPortalRoute,
    metadata: clientPortalMetadata,
  },
  {
    path: "/solutions/compliance",
    label: "Compliance solution page",
    Route: ComplianceRoute,
    metadata: complianceMetadata,
  },
  {
    path: "/solutions/hr",
    label: "HR solution page",
    Route: HRRoute,
    metadata: hrMetadata,
  },
  {
    path: "/solutions/internal-knowledge",
    label: "Internal Knowledge solution page",
    Route: InternalKnowledgeRoute,
    metadata: internalKnowledgeMetadata,
  },
  {
    path: "/solutions/legal",
    label: "Legal solution page",
    Route: LegalRoute,
    metadata: legalMetadata,
  },
  {
    path: "/solutions/operations",
    label: "Operations solution page",
    Route: OperationsRoute,
    metadata: operationsMetadata,
  },
  {
    path: "/solutions/procurement",
    label: "Procurement solution page",
    Route: ProcurementRoute,
    metadata: procurementMetadata,
  },
  {
    path: "/solutions/research",
    label: "Research solution page",
    Route: ResearchRoute,
    metadata: researchMetadata,
  },
  {
    path: "/solutions/sales",
    label: "Sales solution page",
    Route: SalesRoute,
    metadata: salesMetadata,
  },
  {
    path: "/solutions/support",
    label: "Support solution page",
    Route: SupportRoute,
    metadata: supportMetadata,
  },
];

describe("Static solution routes", () => {
  it.each(ROUTES)(
    "$path renders its page inside the labelled main landmark",
    ({ Route, label }) => {
      render(<Route />);

      expect(screen.getByRole("main", { name: label })).toBeInTheDocument();
      expect(
        screen.getAllByRole("heading", { level: 1 }).length,
      ).toBeGreaterThanOrEqual(1);
    },
  );

  it.each(ROUTES)(
    "$path defines a localized canonical URL and a title",
    async ({ metadata, path }) => {
      const result = await metadata({
        params: Promise.resolve({ locale: "de" }),
      });

      expect(result.title).toBeTruthy();
      expect(String(result.alternates?.canonical)).toContain(`/de${path}`);
    },
  );
});
