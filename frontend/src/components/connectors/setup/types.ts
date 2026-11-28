export type ConnectorSetupState = {
  display_name: string;
  external_account_id: string;
  config_values: Record<string, string | boolean>;
  confirmed: boolean;
};
