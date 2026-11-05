--!strict
local initial = noctalia.state.get("snapshot")
local snapshot: Snapshot = (if type(initial) == "table" and initial.version == 1 then initial :: Snapshot else nil) or { version = 1, status = "loading" }
local function formatGoal(goal: number?)
  if snapshot.goal == goal and snapshot.goal_text then
    return snapshot.goal_text
  end
  -- Until the backend presents this goal, avoid guessing locale grouping.
  return tostring(math.floor(goal or 0))
end
local function render()
  local status = snapshot.status or "loading"
  local text = snapshot.steps_text or "—"
  local steps = snapshot.steps
  local goal = noctalia.getConfig("goal")
  local divisor = type(goal) == "number" and goal > 0 and goal < math.huge and goal or 1
  local container = barWidget.isVertical() and ui.column or ui.row
  if snapshot.steps_stale then status = "stale" end
  local color = (status == "connected" or status == "demo") and "primary" or "on_surface_variant"
  barWidget.render(container({ gap = 6, align = "center" }, {
    ui.glyph({ name = "walk", size = 16, color = color }),
    ui.label({ text = text, fontWeight = "Regular" }),
  }))
  local tooltip = noctalia.tr("title") .. " · " .. (snapshot.today_text or snapshot.today or "") .. "\n"
  if steps then
    local percent = (if snapshot.goal == goal and snapshot.goal_percent ~= nil then snapshot.goal_percent else math.floor(steps / divisor * 100))
    tooltip ..= tostring(percent) .. "% · " .. noctalia.tr("goal") .. " " .. formatGoal(goal) .. "\n"
  end
  tooltip ..= noctalia.tr("status." .. status)
  if snapshot.updated_at then tooltip ..= "\n" .. noctalia.tr("fetched") .. " " .. noctalia.formatTime("{:%H:%M}", snapshot.updated_at) end
  barWidget.setTooltip(tooltip)
end
noctalia.state.watch("snapshot", function(value)
  if type(value) == "table" and value.version == 1 then snapshot = value :: Snapshot; render() end
end)
function update()
  noctalia.setUpdateInterval(60000)
  render()
end
function onClick()
  noctalia.togglePanel("democe/fitdash:details")
end
