--!nonstrict
local snapshot = noctalia.state.get("snapshot") or { status = "loading", metrics = {} }
local busy = noctalia.state.get("busy") or false
local confirmation = ""
local counter = 0
local function request(command)
  counter += 1
  confirmation = ""
  noctalia.state.set("request", { command = command, id = tostring(os.time()) .. ":" .. tostring(counter) })
end
local function label(text, props)
  props = props or {}
  props.text = text
  return ui.label(props)
end
local function render()
  local status = snapshot.status or "loading"
  local steps = snapshot.steps
  local goal = noctalia.getConfig("goal")
  local rows = {}
  local previousGroup = ""
  for _, m in ipairs(snapshot.metrics or {}) do
    if m.group ~= previousGroup then
      previousGroup = m.group
      table.insert(rows, label(noctalia.tr("group." .. (m.group or "activity")), {
        color = "primary", fontWeight = "bold", fontSize = 12,
      }))
    end
    local detail = m.period or ""
    if m.status ~= "available" then detail ..= " · " .. noctalia.tr("metric_status." .. m.status) end
    table.insert(rows, ui.row({ gap = 16, align = "center", paddingV = 7 }, {
      ui.column({ flexGrow = 1, gap = 3 }, {
        label(noctalia.tr("metric." .. m.key), { color = "on_surface", fontSize = 14 }),
        label(detail, { color = "on_surface_variant", fontSize = 11 }),
      }),
      label(m.display or "—", { fontWeight = "bold", color = m.status == "stale" and "on_surface_variant" or "on_surface", fontSize = 16 }),
    }))
  end
  if #rows == 0 then
    table.insert(rows, label(noctalia.tr("welcome"), { maxLines = 3, color = "on_surface_variant" }))
  end
  local controls = {
    ui.button({ text = noctalia.tr("refresh"), glyph = "refresh", enabled = not busy,
      onClick = function() request("refresh") end }),
    ui.button({ glyph = "settings", tooltip = noctalia.tr("settings"), onClick = function() noctalia.openSettings() end }),
  }
  local needsAuth = status == "disconnected" or status == "reconnect_required" or # (snapshot.metrics or {}) == 0
  table.insert(controls, ui.button({ text = noctalia.tr(needsAuth and "connect" or "reconnect"), enabled = not busy,
    onClick = function() request("auth") end }))
  if not needsAuth then
    table.insert(controls, ui.button({ glyph = "logout", tooltip = noctalia.tr("disconnect"), enabled = not busy,
      onClick = function() confirmation = "disconnect" render() end }))
  end
  table.insert(controls, ui.button({ glyph = "trash", tooltip = noctalia.tr("clear_cache"), enabled = not busy,
    onClick = function() confirmation = "clear-cache" render() end }))
  local children = {
    ui.row({ gap = 8, align = "center" }, {
      ui.glyph({ name = "walk", color = "primary", size = 22 }),
      label(noctalia.tr("title"), { fontSize = 20, fontWeight = "bold", flexGrow = 1 }),
      ui.button({ glyph = "close", onClick = function() panel.close() end }),
    }),
    ui.column({ gap = 6, padding = 16, radius = 12, fill = "primary/0.10" }, {
      label(snapshot.today or noctalia.tr("today"), { color = "on_surface_variant", fontSize = 12 }),
      label(snapshot.steps_text or "—", { fontSize = 36, fontWeight = "bold", color = "primary" }),
      label(noctalia.tr("steps_goal") .. " " .. tostring(goal), { color = "on_surface_variant" }),
      ui.progress({ progress = steps and math.clamp(steps / goal, 0, 1) or 0, height = 5, fill = "primary", track = "primary/0.15", radius = 3 }),
    }),
    ui.scroll({ flexGrow = 1, gap = 5 }, rows),
    label(noctalia.tr("status." .. status), { color = "on_surface_variant", fontSize = 12, maxLines = 2 }),
  }
  if snapshot.updated_at then
    table.insert(children, label(noctalia.tr("fetched") .. " " .. noctalia.formatTime("{:%H:%M}", snapshot.updated_at), { color = "on_surface_variant", fontSize = 11 }))
  end
  if confirmation ~= "" then
    table.insert(children, label(noctalia.tr(confirmation == "disconnect" and "disconnect_confirm" or "clear_cache_confirm"), { maxLines = 2 }))
    table.insert(children, ui.row({ gap = 8 }, {
      ui.button({ text = noctalia.tr(confirmation == "disconnect" and "disconnect" or "clear_cache"), variant = "destructive", onClick = function() request(confirmation) end }),
      ui.button({ text = noctalia.tr("cancel"), onClick = function() confirmation = "" render() end }),
    }))
  else
    table.insert(children, ui.row({ gap = 8 }, controls))
  end
  panel.render(ui.column({ flexGrow = 1, gap = 12 }, children))
end
noctalia.state.watch("snapshot", function(value)
  if type(value) == "table" then snapshot = value render() end
end)
noctalia.state.watch("busy", function(value) busy = value render() end)
function onOpen(_context)
  render()
  request("status")
end
