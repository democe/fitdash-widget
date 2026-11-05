-- Analysis-only host and JSON boundary types. No runtime import is required.
type Metric = {
  key: string, value: number?, unit: string?, period: string?, status: string?,
  group: string?, fetched_at: number?, display: string?, period_text: string?,
}
type Snapshot = {
  version: number?, status: string?, metrics: {Metric}?, steps: number?,
  steps_text: string?, steps_stale: boolean?, goal: number?, goal_text: string?,
  goal_percent: number?, today: string?, today_text: string?, updated_at: number?,
  updated_date_text: string?,
}
type ProcessResult = { exitCode: number, stdout: string, stdoutTruncated: boolean? }
type GetConfig = (("goal") -> number?)
  & (("interval") -> number)
  & (("backend" | "client" | "units" | "timezone" | "source") -> string)
  & (("sleep" | "vitals" | "demo") -> boolean)
local noctalia: {
  getConfig: GetConfig,
  tr: (string) -> string,
  expandPath: (string) -> string,
  formatTime: (string, number) -> string,
  setUpdateInterval: (number) -> (),
  togglePanel: (string) -> (), openSettings: () -> (),
  copyToClipboard: (string, string) -> boolean,
  notify: (string, string) -> (), notifyError: (string, string) -> (),
  runAsync: ({string}, ((ProcessResult) -> ())?) -> boolean,
  json: { decode: (string) -> unknown },
  state: {
    get: (string) -> unknown,
    set: (string, unknown) -> (),
    watch: (string, (unknown) -> ()) -> (),
  },
} = nil :: any
