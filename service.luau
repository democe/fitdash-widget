--!nonstrict
-- One backend coordinator for every bar instance and the panel.
local busy = false
local authorizing = false
local authStarted = 0
local lastSync = 0
local lastStatus = 0
local state = { version = 1, status = "loading", metrics = {} }
local function publish()
  noctalia.state.set("snapshot", state)
  noctalia.state.set("busy", busy or authorizing)
end
local function arguments(command)
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
local function run(command, force)
  if busy then return end
  local argv = arguments(command)
  if force then table.insert(argv, "--force") end
  busy = true
  publish()
  local launched = noctalia.runAsync(argv, function(result)
    busy = false
    if result.exitCode == 0 and not result.stdoutTruncated then
      local ok, data = pcall(noctalia.json.decode, result.stdout)
      if ok and type(data) == "table" and data.version == 1 then
        if data.status ~= "busy" then state = data end
        if data.status == "authorizing" and not authorizing then
          authorizing = true
          authStarted = os.time()
        end
        if authorizing and data.status ~= "authorizing" and os.time() - authStarted > 3 then
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
  if not launched then
    busy = false
    state.status = "backend_missing"
    publish()
  end
end
function onIpc(event, _payload)
  if noctalia.getConfig("demo") then run("demo") return end
  if event == "status" then run("status") return end
  if busy or authorizing then return end
  if event == "auth" then
    authorizing = true
    authStarted = os.time()
    state.status = "authorizing"
    if not noctalia.runAsync(arguments("auth")) then
      authorizing = false
      state.status = "backend_missing"
    end
    publish()
  elseif event == "refresh" then
    lastSync = os.time()
    run("sync", true)
  elseif event == "disconnect" or event == "clear-cache" then
    lastSync = os.time()
    run(event)
  end
end
noctalia.state.watch("request", function(value)
  if type(value) == "table" then onIpc(value.command, nil) end
end)
function update()
  noctalia.setUpdateInterval(2000)
  local now = os.time()
  if busy then return end
  if noctalia.getConfig("demo") then
    if now - lastStatus >= 10 then lastStatus = now run("demo") end
  elseif authorizing then
    if now - authStarted > 330 then authorizing = false end
    run("status")
  elseif lastStatus == 0 then
    lastStatus = now
    run("status")
  elseif now - lastSync >= noctalia.getConfig("interval") then
    lastSync = now
    run("sync")
  elseif now - lastStatus >= 60 then
    lastStatus = now
    run("status")
  end
end
publish()
