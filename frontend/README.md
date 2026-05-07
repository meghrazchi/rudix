# Frontend

A modern frontend application built with **Next.js App Router**, **React**, **TypeScript**, **Tailwind CSS v4**, and a scalable supporting stack.

## Tech Stack

| Area | Tooling |
|---|---|
| Core framework | Next.js App Router, React, TypeScript |
| Styling | Tailwind CSS v4 |
| UI components | shadcn/ui, Radix UI |
| Icons | lucide-react |
| Forms | React Hook Form, Zod |
| Server state | TanStack Query |
| Client state | Zustand |
| Auth | Auth.js / NextAuth or Clerk |
| Testing | Vitest, React Testing Library, Playwright, MSW |
| Code quality | ESLint, Prettier, TypeScript strict mode |
| Monitoring | Sentry, Google Analytics, Lighthouse |
| Package manager | pnpm |
| Monorepo/build tooling | Turborepo |
| CI/CD | GitLab CI/CD, Docker |
| Animation | Motion |
| Tables/large lists | TanStack Table, TanStack Virtual |
| i18n | next-intl |

## Getting Started

### 1. Clone the repository

```bash
git clone <your-repository-url>
cd rudix/frontend
```

### 2. Install dependencies

```bash
pnpm install
```

If `pnpm` is not installed:

```bash
npm install -g pnpm
```

### 3. Create environment variables

Create a `.env.local` file in the project root:

```bash
cp .env.example .env.local
```

Example:

```env
NEXT_PUBLIC_APP_URL=http://localhost:3000

# Auth
AUTH_SECRET=
AUTH_URL=http://localhost:3000

# Clerk, if using Clerk instead of Auth.js
NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY=
CLERK_SECRET_KEY=

# Sentry
SENTRY_DSN=

# Analytics
NEXT_PUBLIC_GA_ID=
```

### 4. Run the development server

```bash
pnpm dev
```

Open:

```txt
http://localhost:3000
```

## Recommended Project Structure

```txt
.
├── app/
│   ├── layout.tsx
│   ├── page.tsx
│   ├── globals.css
│   ├── api/
│   └── (routes)/
├── components/
│   ├── ui/
│   └── shared/
├── features/
│   └── example/
│       ├── components/
│       ├── hooks/
│       ├── schemas/
│       ├── services/
│       └── types.ts
├── lib/
│   ├── auth.ts
│   ├── env.ts
│   ├── utils.ts
│   └── query-client.ts
├── hooks/
├── stores/
├── styles/
├── tests/
├── public/
├── .env.example
├── next.config.ts
├── package.json
├── tsconfig.json
└── README.md
```

## Scripts

| Command | Description |
|---|---|
| `pnpm dev` | Start the development server |
| `pnpm build` | Build the production app |
| `pnpm start` | Start the production server |
| `pnpm lint` | Run ESLint |
| `pnpm format` | Format code with Prettier |
| `pnpm typecheck` | Run TypeScript checks |
| `pnpm test` | Run unit and component tests |
| `pnpm test:e2e` | Run Playwright end-to-end tests |
| `pnpm test:watch` | Run tests in watch mode |

## Development Guidelines

### Server Components by default

Use Server Components whenever possible.

Use Client Components only when you need:

- Browser APIs
- Event handlers
- Local state
- Effects
- Zustand stores
- TanStack Query hooks
- Animation libraries

Example:

```tsx
'use client';

import { useState } from 'react';

export function Counter() {
  const [count, setCount] = useState(0);

  return <button onClick={() => setCount(count + 1)}>{count}</button>;
}
```

### State management

Use the right state tool for the right job:

| Need | Tool |
|---|---|
| API/server data | TanStack Query |
| Forms | React Hook Form |
| Runtime validation | Zod |
| Client UI state | Zustand |
| URL state | Search params |
| Auth/session state | Auth.js or Clerk |

### Styling

Use Tailwind CSS utility classes for styling.

Use shadcn/ui for reusable UI components.

Use Radix UI directly when you need lower-level accessible primitives.

### Forms

Use:

- React Hook Form for form state
- Zod for validation schemas
- `@hookform/resolvers/zod` to connect both

Example:

```tsx
import { z } from 'zod';

export const loginSchema = z.object({
  email: z.string().email(),
  password: z.string().min(8),
});

export type LoginInput = z.infer<typeof loginSchema>;
```

### API state

Use TanStack Query for:

- Fetching client-side data
- Caching API responses
- Mutations
- Optimistic updates
- Background refetching

Avoid duplicating server state inside Zustand.

### Client state

Use Zustand only for real UI state, such as:

- Open/closed modals
- Selected items
- Temporary filters
- Sidebar state
- Local UI preferences

## Testing

### Unit and component tests

Use Vitest and React Testing Library.

```bash
pnpm test
```

### End-to-end tests

Use Playwright.

```bash
pnpm test:e2e
```

### API mocking

Use MSW for mocking API requests in tests.

## Code Quality

Before opening a pull request, run:

```bash
pnpm typecheck
pnpm lint
pnpm test
pnpm build
```

Recommended rules:

- Keep TypeScript strict mode enabled.
- Prefer explicit types for public functions.
- Keep components small and focused.
- Use feature folders for larger product areas.
- Avoid unnecessary Client Components.
- Avoid storing API data in Zustand.

## Authentication

Choose one auth solution:

### Option 1: Auth.js / NextAuth

Use this when you want:

- Open-source auth
- More ownership and control
- Custom auth flows
- Self-managed providers and adapters

### Option 2: Clerk

Use this when you want:

- Managed authentication
- Prebuilt sign-in/sign-up UI
- Faster setup
- User management dashboard

## Internationalization

Use `next-intl` only when the app needs:

- Multiple languages
- Locale-based routing
- Localized dates
- Localized numbers
- Translation messages

## Performance

Recommended practices:

- Use Server Components by default.
- Split Client Components carefully.
- Use route-level loading states.
- Optimize images with `next/image`.
- Use dynamic imports for heavy client-only modules.
- Use TanStack Virtual for long lists.
- Run Lighthouse audits before release.
- Track runtime errors and performance with Sentry.

## CI/CD

Recommended GitLab pipeline stages:

```yaml
stages:
  - install
  - quality
  - test
  - build
  - deploy
```

A pull request should run:

1. Install dependencies
2. Typecheck
3. Lint
4. Run tests
5. Build the app
6. Optionally deploy a preview environment

## Docker

Basic production Docker flow:

```bash
docker build -t project-name .
docker run -p 3000:3000 project-name
```

## Documentation

Useful docs:

- [Next.js App Router](https://nextjs.org/docs/app)
- [React](https://react.dev/)
- [TypeScript](https://www.typescriptlang.org/docs/)
- [Tailwind CSS](https://tailwindcss.com/docs)
- [shadcn/ui](https://ui.shadcn.com/docs)
- [Radix UI](https://www.radix-ui.com/primitives/docs/overview/introduction)
- [Lucide React](https://lucide.dev/guide/packages/lucide-react)
- [React Hook Form](https://react-hook-form.com/docs)
- [Zod](https://zod.dev/)
- [TanStack Query](https://tanstack.com/query/latest/docs/framework/react/overview)
- [Zustand](https://zustand.docs.pmnd.rs/)
- [Auth.js](https://authjs.dev/getting-started)
- [Clerk](https://clerk.com/docs/quickstarts/nextjs)
- [Vitest](https://vitest.dev/guide/)
- [Testing Library](https://testing-library.com/docs/react-testing-library/intro/)
- [Playwright](https://playwright.dev/docs/intro)
- [MSW](https://mswjs.io/docs/)
- [ESLint](https://eslint.org/docs/latest/)
- [Prettier](https://prettier.io/docs/)
- [Sentry for Next.js](https://docs.sentry.io/platforms/javascript/guides/nextjs/)
- [pnpm](https://pnpm.io/)
- [Turborepo](https://turbo.build/repo/docs)
- [GitLab CI/CD](https://docs.gitlab.com/ci/)
- [Docker](https://docs.docker.com/)
- [Motion](https://motion.dev/docs/react)
- [TanStack Table](https://tanstack.com/table/latest/docs/introduction)
- [TanStack Virtual](https://tanstack.com/virtual/latest/docs/introduction)
- [next-intl](https://next-intl.dev/docs/getting-started/app-router)

## License

Add your license here.

```txt
MIT
```
