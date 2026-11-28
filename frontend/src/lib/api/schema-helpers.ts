// Type-only helpers for adapting generated OpenAPI schemas (R07-05).
//
// openapi-typescript marks a response field as optional when the Pydantic model gives it a
// default, even when the server always sends it. These helpers let a client module keep the
// generated type as the source of truth and state the few places where the frontend differs.
// No runtime effect.

/** Keep `K` required in the generated type `T` (server-defaulted fields that are always sent). */
export type WithRequired<T, K extends keyof T> = Omit<T, K> &
  Required<Pick<T, K>>;

/** Make `K` optional in the generated type `T` (fields fixtures and requests may omit). */
export type WithOptional<T, K extends keyof T> = Omit<T, K> &
  Partial<Pick<T, K>>;

/** Replace the fields of `Base` that `Extra` declares with the frontend's own types. */
export type Overlay<Base, Extra> = Omit<Base, keyof Extra> & Extra;

/**
 * A response body as the server sends it. FastAPI serialises every model field, defaults
 * included, so a field the schema marks optional because Pydantic gives it a default is always
 * present on the wire. Applies recursively; `null` stays in the type, `undefined` does not.
 * Use for response types only, never for request bodies.
 */
export type Served<T> = T extends readonly (infer U)[]
  ? Served<U>[]
  : T extends (...args: never[]) => unknown
    ? T
    : T extends object
      ? { [K in keyof T]-?: Served<Exclude<T[K], undefined>> }
      : T;
