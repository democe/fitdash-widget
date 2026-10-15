-- Analysis-only host declarations, prepended by tests/check_luau_types.py.
-- Keep properties aligned with the subset used by FitDash.
type UIProps = {
  text: string?, name: string?, glyph: string?, tooltip: string?,
  color: string?, fill: string?, track: string?, fontWeight: string?,
  align: string?, variant: string?, fontSize: number?, size: number?,
  gap: number?, padding: number?, paddingV: number?, radius: number?,
  flexGrow: number?, maxLines: number?, height: number?, progress: number?,
  enabled: boolean?, onClick: (() -> ())?,
}
type UINode = { props: UIProps, children: {UINode}? }
type Container = (UIProps, {UINode}) -> UINode
type Control = (UIProps) -> UINode
local ui: {
  row: Container, column: Container, scroll: Container,
  label: Control, glyph: Control, button: Control, progress: Control,
} = nil :: any
local barWidget: {
  render: (UINode) -> (), isVertical: () -> boolean, setTooltip: (string) -> (),
} = nil :: any
local panel: { render: (UINode) -> (), close: () -> () } = nil :: any
