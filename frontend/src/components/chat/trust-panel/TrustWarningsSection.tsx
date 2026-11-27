import { WarningBanner } from "@/components/chat/trust-panel/TrustPrimitives";
import { trackFeatureEvent } from "@/lib/analytics";

export function TrustWarningsSection({
  warnings,
  messageId,
}: {
  warnings: string[];
  messageId: string;
}) {
  return (
    <>
      {warnings.length > 0 && (
        <div
          className="space-y-2 px-4 pt-4 md:px-6 md:pt-5"
          onClick={() => {
            void trackFeatureEvent("feature.chat.trust_panel_warning_clicked", {
              surface: "app",
              route: "/chat",
              pageKey: "chat",
              featureArea: "chat",
              entityId: messageId,
              count: warnings.length,
              dedupeKey: `chat-trust-panel-warning-${messageId}`,
            });
          }}
        >
          {warnings.map((w, i) => (
            <WarningBanner
              key={i}
              tone={
                w ===
                "Low confidence — validate this answer against cited sources."
                  ? "neutral"
                  : "warning"
              }
            >
              {w}
            </WarningBanner>
          ))}
        </div>
      )}
    </>
  );
}
