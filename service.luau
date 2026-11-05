--!strict
-- One backend coordinator for every bar instance and the panel.
local busy = false
local busyStarted = 0
local currentRun = 0
local authorizing = false
local authStarted = 0
local lastSync = 0
local lastStatus = 0
local state: Snapshot = { version = 1, status = "loading", metrics = {} }
local function publish()
  noctalia.state.set("snapshot", state)
  noctalia.state.set("busy", busy or authorizing)
end
local function arguments(command: string)
  return {
    noctalia.expandPath(noctalia.getConfig("backend")), command,
    "--client", noctalia.expandPath(noctalia.getConfig("client")),
    "--interval", tostring(noctalia.getConfig("interval")),
    "--goal", tostring(noctalia.getConfig("goal")),
    "--units", noctalia.getConfig("units"),
    "--timezone", noctalia.getConfig("timezone"),
    "--source", noctalia.getConfig("source"),
    noctalia.getConfig("sleep") and "--sleep" or "--no-sleep",
    noctalia.getConfig("vitals") and "--vitals" or "--no-vitals",
  }
end
-- Validate untyped JSON before handing it to the strictly typed renderers.
local function validFields(value: {[string]: unknown}, strings: {string}, numbers: {string}): boolean
  for _, key in ipairs(strings) do
    if value[key] ~= nil and type(value[key]) ~= "string" then return false end
  end
  for _, key in ipairs(numbers) do
    local n = value[key]
    if n ~= nil and (type(n) ~= "number" or n ~= n or n < 0 or n >= math.huge) then return false end
  end
  return true
end
local function validSnapshot(value: unknown): boolean
  if type(value) ~= "table" then return false end
  local data = value :: {[string]: unknown}
  if data.version ~= 1 or type(data.status) ~= "string" then return false end
  if not validFields(data,
    {"steps_text", "goal_text", "today", "today_text", "updated_date_text"},
    {"steps", "goal", "goal_percent", "updated_at"}) then return false end
  if data.steps_stale ~= nil and type(data.steps_stale) ~= "boolean" then return false end
  if data.metrics == nil then return data.status == "busy" end
  if type(data.metrics) ~= "table" then return false end
  local metrics = data.metrics :: {[unknown]: unknown}
  local count = 0
  for index, entry in pairs(metrics) do
    count += 1
    if type(index) ~= "number" or index < 1 or index % 1 ~= 0 or type(entry) ~= "table" then return false end
    local m = entry :: {[string]: unknown}
    if type(m.key) ~= "string" or not validFields(m,
      {"unit", "period", "period_text", "status", "group", "display"},
      {"value", "fetched_at"}) then return false end
  end
  return count == #metrics
end
local function run(command: string, force: boolean?)
  if busy then return end
  local argv = arguments(command)
  if force then table.insert(argv, "--force") end
  busy = true
  busyStarted = os.time()
  currentRun += 1
  local runId = currentRun
  publish()
  local ok, launched = pcall(noctalia.runAsync, argv, function(result)
    if runId ~= currentRun then return end
    busy = false
    if result.exitCode == 0 and not result.stdoutTruncated then
      local decodeOk, data = pcall(noctalia.json.decode, result.stdout)
      if decodeOk and validSnapshot(data) then
        local decoded = data :: Snapshot
        if decoded.status ~= "busy" then state = decoded end
        if decoded.status == "authorizing" and not authorizing then
          authorizing = true
          authStarted = os.time()
        end
        if authorizing and decoded.status ~= "authorizing" and os.time() - authStarted > 3 then
          authorizing = false
          lastSync = 0
        end
      else
        state.status = "backend_error"
      end
    else
      state.status = "backend_error"
    end
    publish()
  end)
  if not ok or not launched then
    busy = false
    state.status = "backend_missing"
    publish()
  end
end
function onIpc(event: string, _payload: unknown)
  if event == "status" then
    run(if noctalia.getConfig("demo") then "demo" else "status")
    return
  end
  if busy or authorizing then return end
  if event == "auth" then
    authorizing = true
    authStarted = os.time()
    lastStatus = 0
    state.status = "authorizing"
    local ok, launched = pcall(function()
      return noctalia.runAsync(arguments("auth"))
    end)
    if not ok or not launched then
      authorizing = false
      state.status = "backend_missing"
    end
    publish()
  elseif event == "refresh" then
    lastSync = os.time()
    if noctalia.getConfig("demo") then
      run("demo")
    else
      run("sync", true)
    end
  elseif event == "disconnect" or event == "clear-cache" then
    lastSync = os.time()
    run(event)
  end
end
noctalia.state.watch("request", function(value)
  if type(value) == "table" and type(value.command) == "string" then onIpc(value.command, nil) end
end)
function update()
  noctalia.setUpdateInterval(2000)
  local now = os.time()
  if busy then
    if now - busyStarted > 45 then
      busy = false
      currentRun += 1
      state.status = "backend_error"
      publish()
    end
    return
  end
  if noctalia.getConfig("demo") then
    if now - lastStatus >= 10 then lastStatus = now; run("demo") end
  elseif authorizing then
    if now - authStarted > 330 then authorizing = false end
    if now - lastStatus >= 5 then
      lastStatus = now
      run("status")
    end
  elseif lastStatus == 0 then
    lastStatus = now
    run("status")
  elseif now - lastSync >= noctalia.getConfig("interval") then
    lastSync = now
    run("sync")
  elseif now - lastStatus >= 180 then
    lastStatus = now
    run("status")
  end
end
publish()
