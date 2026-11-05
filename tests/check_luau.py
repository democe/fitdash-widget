"""Exercise Noctalia entry behavior in a real Luau VM with host stubs."""

import os
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MOCK = r"""
local config = {goal = 10000, interval = 300, backend = "/backend path/fitdash", client = "/client.json", units = "auto", timezone = "", source = "all-sources", sleep = true, vitals = true, demo = false}
local watches, values, processes = {}, {}, {}
local tree, tooltip, opened, closed
local asyncCallback
local now = 1000
os = {time = function() return now end}
noctalia = {
 getConfig = function(k) return config[k] end,
 tr = function(k) return k end,
 expandPath = function(p) return p end,
 formatTime = function(...) return "10:00" end,
 setUpdateInterval = function(ms) assert(ms >= 1000) end,
 togglePanel = function(id) opened = id end,
 openSettings = function() opened = "settings" end,
 copyToClipboard = function(text, mime) values.clipboard = text values.mime = mime return not values.copyFails end,
 notify = function(title, message) values.notice = message end,
 notifyError = function(title, message) values.error = message end,
 runAsync = function(argv, cb) table.insert(processes, argv) asyncCallback = cb return true end,
 json = {decode = function(text) return values.response end},
 state = {
  get = function(k) return values[k] end,
  set = function(k,v) values[k] = v end,
  watch = function(k,fn) watches[k] = fn end,
 },
}
ui = {}
for _,kind in ipairs({"row", "column", "glyph", "label", "progress", "button", "scroll"}) do
 ui[kind] = function(props, children) return {kind=kind, props=props, children=children} end
end
barWidget = {
 render = function(t) tree = t end,
 isVertical = function() return values.vertical or false end,
 setTooltip = function(t) tooltip = t end,
}
panel = {render = function(t) tree = t end, close = function() closed = true end}
"""
CHECKS = {
    "widget.luau": r"""
update()
assert(tree.kind == "row")
watches.snapshot({version=1,status="connected", steps=0, steps_text="0", today="2026-09-21"})
assert(tree.children[2].props.text == "0")
watches.snapshot({version=2, status="connected", steps_text="bad"})
assert(tree.children[2].props.text == "0")
watches.snapshot({status="connected", steps_text="bad"})
assert(tree.children[2].props.text == "0")
watches.snapshot({version=1,status="connected", steps=0, steps_text="0", today="2026-09-21", today_text="21-09-2026"})
assert(string.find(tooltip, "21-09-2026", 1, true))
assert(not string.find(tooltip, "2026-09-21", 1, true))
watches.snapshot({version=1,status="connected", steps=12, steps_text="12", goal=10000, goal_text="10\u{202f}000"})
assert(string.find(tooltip, "10\u{202f}000", 1, true))
config.goal = 12500
update()
assert(string.find(tooltip, "12500", 1, true))
config.goal = 10000
for _, goal in ipairs({0, -1, math.huge}) do
 config.goal = goal
 update()
 assert(not string.find(tooltip, "inf%%"))
end
config.goal = nil
update()
assert(not string.find(tooltip, "inf%%"))
config.goal = 10000
values.vertical = true
update()
assert(tree.kind == "column")
onClick()
assert(opened == "democe/fitdash:details")
""",
    "panel.luau": r"""
onOpen(nil)
assert(tree.kind == "column")
assert(values.request.command == "status")
watches.snapshot({version=1,status="connected",steps=12,steps_text="12",metrics={{key="steps",value=12,display="12",period="2026-09-21",group="activity",status="available"}}})
assert(tree.children[2].children[2].props.text == "12")
watches.snapshot({version=2, status="connected", steps_text="bad"})
assert(tree.children[2].children[2].props.text == "12")
watches.snapshot({status="connected", steps_text="bad"})
assert(tree.children[2].children[2].props.text == "12")
watches.snapshot({version=1,status="connected", steps=12, steps_text="12", goal=10000, goal_text="10\u{202f}000", metrics={}})
assert(string.find(tree.children[2].children[3].props.text, "10\u{202f}000", 1, true))
config.goal = 12500
watches.busy(false)
assert(string.find(tree.children[2].children[3].props.text, "12500", 1, true))
config.goal = 10000
for _, goal in ipairs({0, -1, math.huge}) do
 config.goal = goal
 watches.busy(false)
 assert(tree.children[2].children[4].props.progress == 1)
end
config.goal = nil
watches.busy(false)
assert(tree.children[2].children[4].props.progress == 1)
config.goal = 10000
watches.busy(false)
local controls = tree.children[#tree.children]
controls.children[1].props.onClick()
assert(values.request.command == "refresh")
watches.busy(true)
assert(tree.children[#tree.children].children[1].props.enabled == false)

config.sleep = false
config.vitals = true
watches.snapshot({version=1,status="connected",today="2026-09-21",today_text="21-09-2026",steps=0,steps_text="0",metrics={
 {key="steps",display="0",period="2026-09-21",group="activity",status="available"},
 {key="distance",display="1.25 mi",period="2026-09-21",period_text="21-09-2026",group="activity",status="available"},
 {key="sleep",display="7 h 00 min",period="2026-09-21",group="sleep",status="available"},
 {key="hrv",period="2026-09-20",group="vitals",status="no_data"},
 {key="resting-heart-rate",display="60 bpm",period="2026-09-20",group="vitals",status="stale"},
}})
local copy = tree.children[1].children[3]
assert(copy.props.glyph == "copy" and copy.props.enabled)
copy.props.onClick()
assert(values.mime == "text/plain")
assert(string.find(values.clipboard, "| copy.metric | copy.value | copy.date | copy.status |\n| ----- | ----- | ----- | ----- |", 1, true))
assert(string.find(values.clipboard, "copy.date: 21-09-2026", 1, true))
assert(string.find(values.clipboard, "metric.steps: 0", 1, true))
assert(string.find(values.clipboard, "settings.goal: 10000", 1, true))
assert(string.find(values.clipboard, "| metric.distance | 1.25 mi | 21-09-2026 | metric_status.available |", 1, true))
assert(not string.find(values.clipboard, "metric.sleep", 1, true))
assert(string.find(values.clipboard, "| metric.hrv | — | 2026-09-20 | metric_status.no_data |", 1, true))
assert(string.find(values.clipboard, "| metric.resting-heart-rate | 60 bpm | 2026-09-20 | metric_status.stale |", 1, true))
assert(values.notice == "copy.success")
values.copyFails = true
copy.props.onClick()
assert(values.error == "copy.failed")
watches.snapshot({version=1,status="loading",metrics={}})
assert(tree.children[1].children[3].props.enabled == false)
watches.snapshot({version=1,status="cache_cleared",metrics={}})
local clearedControls = tree.children[#tree.children].children
assert(clearedControls[3].props.text == "reconnect")
assert(clearedControls[4].props.glyph == "logout")
watches.snapshot({version=1,status="disconnected",metrics={}})
local disconnectedControls = tree.children[#tree.children].children
assert(disconnectedControls[3].props.text == "connect")
assert(disconnectedControls[4].props.glyph == "trash")
watches.snapshot({version=1,status="connected",metrics={
 {key="steps",display="10|000\nsteps",period="2026-09-21",group="activity",status="available"},
}})
values.copyFails = false
copy.props.onClick()
assert(string.find(values.clipboard, "| metric.steps | 10\\|000 steps | 2026-09-21 | metric_status.available |", 1, true))
""",
    "service.luau": r"""
update()
assert(processes[1][1] == "/backend path/fitdash")
assert(processes[1][2] == "status")
update()
assert(#processes == 1)
values.response = {version=1,status="connected",metrics={}}
asyncCallback({exitCode=0,stdout="json"})
assert(values.snapshot.status == "connected")
for _, response in ipairs({
 {version=2,status="connected",metrics={}},
 {status="connected",metrics={}},
 {version=1,status=42,metrics={}},
 {version=1,status="connected",metrics="bad"},
 {version=1,status="connected",metrics={{key="steps",display={}}}},
 {version=1,status="connected",metrics={},steps=math.huge},
 {version=1,status="connected",metrics={},steps=0/0},
}) do
 values.response = response
 onIpc("status", nil)
 asyncCallback({exitCode=0,stdout="json"})
 assert(values.snapshot.status == "backend_error")
 assert(values.busy == false)
end
values.response = {version=1,status="connected",metrics={}}
-- Reset captured launches so the remaining tests retain their numbering.
processes = {processes[1]}
watches.request({command="refresh", id="1"})
assert(processes[2][2] == "sync")
assert(processes[2][#processes[2]] == "--force")
onIpc("refresh", nil)
assert(#processes == 2)
asyncCallback({exitCode=0,stdout="json"})
onIpc("auth", nil)
assert(processes[3][2] == "auth")
assert(values.busy == true)
-- Finish authorizing by running status with connected status after 4 seconds
now = now + 4
onIpc("status", nil)
values.response = {version=1,status="connected",metrics={}}
asyncCallback({exitCode=0,stdout="json"})
assert(values.busy == false)
-- Demo mode should only substitute demo for status and refresh, not swallow auth/disconnect/clear-cache
config.demo = true
processes = {}
onIpc("status", nil)
assert(processes[1][2] == "demo")
asyncCallback({exitCode=0,stdout="json"})
onIpc("refresh", nil)
assert(processes[2][2] == "demo")
asyncCallback({exitCode=0,stdout="json"})
onIpc("disconnect", nil)
assert(processes[3][2] == "disconnect")
asyncCallback({exitCode=0,stdout="json"})
onIpc("clear-cache", nil)
assert(processes[4][2] == "clear-cache")
asyncCallback({exitCode=0,stdout="json"})
onIpc("auth", nil)
assert(processes[5][2] == "auth")
-- Finish authorizing again
now = now + 4
onIpc("status", nil)
values.response = {version=1,status="connected",metrics={}}
asyncCallback({exitCode=0,stdout="json"})
assert(values.busy == false)
config.demo = false
-- Watchdog clears busy when backend hangs past timeout
onIpc("refresh", nil)
assert(values.busy == true)
local hungCallback = asyncCallback
now = now + 10
update()
assert(values.busy == true)
now = now + 40
update()
assert(values.busy == false)
assert(values.snapshot.status == "backend_error")
-- Late callback from timed-out run should be ignored
values.response = {version=1,status="connected",metrics={}}
hungCallback({exitCode=0,stdout="json"})
assert(values.snapshot.status == "backend_error")
-- Authorizing should throttle status polls to 5 seconds
onIpc("auth", nil)
processes = {}
asyncCallback = nil
update()
assert(#processes == 1)
assert(processes[1][2] == "status")
if asyncCallback then asyncCallback({exitCode=0,stdout="json"}) end
now = now + 2
update()
assert(#processes == 1)
now = now + 3
update()
assert(#processes == 2)
assert(processes[2][2] == "status")
""",
}

if __name__ == "__main__":
    binary = os.environ.get("LUAU", "luau")
    for source, checks in CHECKS.items():
        with tempfile.NamedTemporaryFile(mode="w", suffix=".luau") as script:
            script.write(MOCK + "\n" + (ROOT / source).read_text() + "\n" + checks)
            script.flush()
            subprocess.run([binary, script.name], check=True)
        print(source + ": passed")
