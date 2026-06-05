import type { WizardStepProps } from "@/components/connectors/wizard/types";
import type { JiraWizardState, SyncSchedule } from "../JiraWizard.types";

type ScheduleOption = {
  value: SyncSchedule;
  icon: string;
  label: string;
  sublabel: string;
};

const SCHEDULES: ScheduleOption[] = [
  { value: "realtime", icon: "bolt", label: "Real-time", sublabel: "Webhooks" },
  { value: "hourly", icon: "schedule", label: "Hourly", sublabel: "Polling" },
  { value: "daily", icon: "event", label: "Daily", sublabel: "Midnight" },
  { value: "weekly", icon: "calendar_month", label: "Weekly", sublabel: "Weekends" },
];

export function JiraSyncStep({ state, onChange }: WizardStepProps<JiraWizardState>) {
  return (
    <div>
      <h2 className="text-2xl font-semibold tracking-tight text-[#1b1b24] mb-1">
        Sync Configuration
      </h2>
      <p className="text-base text-[#464555] mb-8">
        Determine how frequently Rudix should poll Jira for new updates.
      </p>

      <div className="bg-[#f5f2ff] p-8 rounded-2xl border border-[#c7c4d8]">
        <label className="block text-sm font-semibold text-[#1b1b24] mb-5">
          Refresh Interval
        </label>

        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          {SCHEDULES.map((s) => {
            const active = state.syncSchedule === s.value;
            return (
              <button
                key={s.value}
                type="button"
                onClick={() => onChange({ syncSchedule: s.value })}
                className={`py-6 px-4 rounded-xl flex flex-col items-center gap-2 transition-all border-2 ${
                  active
                    ? "border-[#3525cd] bg-white text-[#3525cd] shadow-sm"
                    : "border-[#c7c4d8] bg-white text-[#464555] hover:border-[#3525cd]/40"
                }`}
              >
                <span className="material-symbols-outlined text-[28px]">{s.icon}</span>
                <span className="font-bold text-sm">{s.label}</span>
                <span className="text-[10px] uppercase font-semibold tracking-wide opacity-70">
                  {s.sublabel}
                </span>
              </button>
            );
          })}
        </div>

        {/* Full re-index toggle */}
        <div className="mt-8 pt-6 border-t border-[#c7c4d8]">
          <div className="flex items-center justify-between mb-2">
            <span className="font-semibold text-sm text-[#1b1b24]">
              Full Re-index (Optional)
            </span>
            <button
              type="button"
              onClick={() => onChange({ fullReindex: !state.fullReindex })}
              className={`w-12 h-6 rounded-full relative transition-colors ${
                state.fullReindex ? "bg-[#3525cd]" : "bg-[#c7c4d8]"
              }`}
            >
              <span
                className={`absolute top-1 w-4 h-4 bg-white rounded-full shadow transition-all ${
                  state.fullReindex ? "left-7" : "left-1"
                }`}
              />
            </button>
          </div>
          <p className="text-sm text-[#464555]">
            Wipes existing index and re-syncs all historical data once every 30
            days to ensure consistency.
          </p>
        </div>
      </div>
    </div>
  );
}
