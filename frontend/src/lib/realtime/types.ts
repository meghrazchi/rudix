/**
 * Realtime event envelope (R07-07, contract 4.2.6). Hand-written because SSE frames are
 * not part of the OpenAPI schema. Payloads carry ids and statuses only.
 */

export type RealtimeStatus =
  | "disabled"
  | "connecting"
  | "connected"
  | "unavailable";

type Envelope<TType extends string, TPayload> = {
  type: TType;
  organization_id: string;
  occurred_at: string;
  payload: TPayload;
};

export type DocumentStatusEvent = Envelope<
  "document.status",
  { document_id: string; status: string }
>;
export type DocumentsChangedEvent = Envelope<
  "documents.changed",
  Record<string, never>
>;
export type NotificationCreatedEvent = Envelope<
  "notification.created",
  { notification_id: string }
>;
export type ConnectorSyncEvent = Envelope<
  "connector.sync",
  { connection_id: string; run_id: string; status: string }
>;
export type AgentRunEvent = Envelope<
  "agent.run",
  { run_id: string; status: string }
>;
export type IncidentEvent = Envelope<
  "incident",
  { incident_id: string; status: string }
>;

export type RealtimeEvent =
  | DocumentStatusEvent
  | DocumentsChangedEvent
  | NotificationCreatedEvent
  | ConnectorSyncEvent
  | AgentRunEvent
  | IncidentEvent;

export type RealtimeEventType = RealtimeEvent["type"];

const PAYLOAD_KEYS: Record<RealtimeEventType, readonly string[]> = {
  "document.status": ["document_id", "status"],
  "documents.changed": [],
  "notification.created": ["notification_id"],
  "connector.sync": ["connection_id", "run_id", "status"],
  "agent.run": ["run_id", "status"],
  incident: ["incident_id", "status"],
};

export const REALTIME_EVENT_TYPES = Object.keys(
  PAYLOAD_KEYS,
) as RealtimeEventType[];

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

/** Parse the `data` of a frame; anything malformed or of an unknown type is `null`. */
export function parseRealtimeEvent(
  eventName: string,
  data: string,
): RealtimeEvent | null {
  let value: unknown;
  try {
    value = JSON.parse(data);
  } catch {
    return null;
  }
  if (!isRecord(value) || !isRecord(value.payload)) {
    return null;
  }
  const type = value.type;
  if (
    typeof type !== "string" ||
    type !== eventName ||
    !(type in PAYLOAD_KEYS)
  ) {
    return null;
  }
  if (typeof value.organization_id !== "string") {
    return null;
  }
  const payload: Record<string, string> = {};
  for (const key of PAYLOAD_KEYS[type as RealtimeEventType]) {
    const field = value.payload[key];
    if (typeof field !== "string") {
      return null;
    }
    payload[key] = field;
  }
  return {
    type,
    organization_id: value.organization_id,
    occurred_at: typeof value.occurred_at === "string" ? value.occurred_at : "",
    payload,
  } as RealtimeEvent;
}
