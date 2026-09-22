"""Exercise Noctalia entry behavior in a real Luau VM with host stubs."""

import os
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
MOCK = r"""
local config = {goal = 10000, interval = 300, backend = "/backend path/fitdash", client = "/client.json", units = "auto", timezone = "", source = "all-sources", sleep = true, vitals = true, demo = false}
local watches, values, processes = {}, {}, {}
local tree, tooltip, opened, closed
local asyncCallback
local now = 1000
os = {time = function() return now end}
noctalia = {
 getConfig = function(k) assert(config[k] ~= nil, k) return config[k] end,
 tr = function(k) return k end,
 expandPath = function(p) return p end,
 formatTime = function(...) return "10:00" end,
 setUpdateInterval = function(ms) assert(ms >= 1000) end,
 togglePanel = function(id) opened = id end,
 openSettings = function() opened = "settings" end,
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
watches.snapshot({status="connected", steps=0, steps_text="0", today="2026-09-21"})
assert(tree.children[2].props.text == "0")
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
watches.snapshot({status="connected",steps=12,steps_text="12",metrics={{key="steps",value=12,display="12",period="2026-09-21",group="activity",status="available"}}})
assert(tree.children[2].children[2].props.text == "12")
local controls = tree.children[#tree.children]
controls.children[1].props.onClick()
assert(values.request.command == "refresh")
watches.busy(true)
assert(tree.children[#tree.children].children[1].props.enabled == false)
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
watches.request({command="refresh", id="1"})
assert(processes[2][2] == "sync")
assert(processes[2][#processes[2]] == "--force")
onIpc("refresh", nil)
assert(#processes == 2)
asyncCallback({exitCode=0,stdout="json"})
onIpc("auth", nil)
assert(processes[3][2] == "auth")
assert(values.busy == true)
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
