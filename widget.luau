--!nonstrict
local snapshot = noctalia.state.get("snapshot") or { status = "loading" }
local function render()
  local status = snapshot.status or "loading"
  local text = snapshot.steps_text or "—"
  local steps = snapshot.steps
  local goal = noctalia.getConfig("goal")
  local container = barWidget.isVertical() and ui.column or ui.row
  if snapshot.steps_stale then status = "stale" end
  local color = (status == "connected" or status == "demo") and "primary" or "on_surface_variant"
  barWidget.render(container({ gap = 6, align = "center" }, {
    ui.glyph({ name = "walk", size = 16, color = color }),
    ui.label({ text = text, fontWeight = "Regular" }),
  }))
  local tooltip = noctalia.tr("title") .. " · " .. (snapshot.today or "") .. "\n"
  if steps then tooltip ..= tostring(math.floor(steps / goal * 100)) .. "% · " .. noctalia.tr("goal") .. " " .. tostring(goal) .. "\n" end
  tooltip ..= noctalia.tr("status." .. status)
  if snapshot.updated_at then tooltip ..= "\n" .. noctalia.tr("fetched") .. " " .. noctalia.formatTime("{:%H:%M}", snapshot.updated_at) end
  barWidget.setTooltip(tooltip)
end
noctalia.state.watch("snapshot", function(value)
  if type(value) == "table" then snapshot = value render() end
end)
function update()
  noctalia.setUpdateInterval(60000)
  render()
end
function onClick()
  noctalia.togglePanel("democe/fitdash:details")
end
