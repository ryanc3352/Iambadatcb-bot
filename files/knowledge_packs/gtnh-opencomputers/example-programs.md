# Example OpenComputers programs for GTNH (tested Lua 5.3)

## Example: machine status board
Shows every GregTech machine connected through adapters: name, running or idle, progress and maintenance problems. Save as `status.lua`, run `status`.
```lua
local component = require("component")
local term = require("term")
local gpu = component.gpu

local function problems(m)
  for _, line in ipairs(m.getSensorInformation()) do
    local n = line:gsub("§.", ""):match("Problems:%s*(%d+)")
    if n then return tonumber(n) end
  end
  return 0
end

while true do
  term.clear()
  local row = 1
  for address in component.list("gt_machine") do
    local m = component.proxy(address)
    local max = m.getWorkMaxProgress()
    local state = not m.isWorkAllowed() and "OFF" or m.isMachineActive() and "running" or "idle"
    local pct = max > 0 and string.format("%3d%%", m.getWorkProgress() * 100 // max) or "    "
    local p = problems(m)
    gpu.setForeground(p > 0 and 0xFF5555 or state == "running" and 0x55FF55 or 0xAAAAAA)
    gpu.set(1, row, string.format("%-30s %-8s %s%s", m.getName():sub(1, 30), state, pct,
                                 p > 0 and ("  " .. p .. " problems") or ""))
    row = row + 1
  end
  gpu.setForeground(0xFFFFFF)
  os.sleep(5)
end
```

## Example: alarm when a machine stops
Beeps and turns on a redstone signal (wire it to note blocks or an alarm) when a machine needs maintenance, was turned off, or wants to run but can't for over a minute. Needs a redstone card in the computer.
```lua
local component = require("component")
local computer = require("computer")
local sides = require("sides")
local rs = component.redstone
local stuck = {}   -- address -> uptime when it first had work but wasn't running

local function problems(m)
  for _, line in ipairs(m.getSensorInformation()) do
    local n = line:gsub("§.", ""):match("Problems:%s*(%d+)")
    if n then return tonumber(n) end
  end
  return 0
end

while true do
  local bad = {}
  for address in component.list("gt_machine") do
    local m = component.proxy(address)
    if m.hasWork() and not m.isMachineActive() then
      stuck[address] = stuck[address] or computer.uptime()
    else
      stuck[address] = nil
    end
    if problems(m) > 0 then bad[#bad + 1] = m.getName() .. ": maintenance"
    elseif not m.isWorkAllowed() then bad[#bad + 1] = m.getName() .. ": turned off"
    elseif stuck[address] and computer.uptime() - stuck[address] > 60 then bad[#bad + 1] = m.getName() .. ": stuck" end
  end
  rs.setOutput(sides.top, #bad > 0 and 15 or 0)
  if #bad > 0 then
    print(table.concat(bad, ", "))
    computer.beep(1200, 0.4)
  end
  os.sleep(5)
end
```

## Example: power monitor that pauses big machines
Reads the Lapotronic Supercapacitor; below 20% it pauses the listed machines with `setWorkAllowed(false)`, above 50% it starts them again. Put the machines' addresses (from the `components` command) in `heavy`.
```lua
local component = require("component")
local lsc = component.LSC
local heavy = {"3f2a", "b81c"}       -- start of each machine's address
local paused = false

local function setAll(allowed)
  for _, short in ipairs(heavy) do
    component.proxy(component.get(short)).setWorkAllowed(allowed)
  end
end

local last = lsc.getStoredEU()
while true do
  os.sleep(20)
  local stored, capacity = lsc.getStoredEU(), lsc.getEUCapacity()
  local percent = capacity > 0 and stored / capacity * 100 or 0
  local perTick = (stored - last) / 400          -- 20 seconds = 400 ticks
  last = stored
  print(string.format("%.1f%%  %+.0f EU/t", percent, perTick))
  if percent < 20 and not paused then setAll(false); paused = true; print("paused heavy machines")
  elseif percent > 50 and paused then setAll(true); paused = false; print("started heavy machines") end
end
```

## Example: AE2 stock keeper
Keeps items stocked by requesting crafts when they run low. Needs an adapter on an ME interface or controller. Each entry: item label, how many to keep, how many to craft at once.
```lua
local component = require("component")
local me = component.me_interface
local keep = {
  {label = "Steel Plate", amount = 256, batch = 64},
  {label = "Electronic Circuit", amount = 32, batch = 16},
}
local crafting = {}   -- label -> status object of the job we started

while true do
  for _, want in ipairs(keep) do
    local job = crafting[want.label]
    if job and (job.isDone() or job.isCanceled()) then crafting[want.label] = nil; job = nil end
    if not job then
      local found = me.getItemsInNetwork({label = want.label})
      local have = found[1] and found[1].size or 0
      if have < want.amount then
        local recipe = me.getCraftables({label = want.label})[1]
        if recipe then
          crafting[want.label] = recipe.request(want.batch)
          print("crafting " .. want.batch .. " " .. want.label .. " (have " .. have .. ")")
        else
          print("no pattern for " .. want.label)
        end
      end
    end
  end
  os.sleep(30)
end
```

## Example: send a message to Discord
Posts to a Discord channel webhook (Discord channel settings > Integrations > Webhooks). Needs an internet card. Keep the webhook URL secret: anyone with it can post.
```lua
local internet = require("internet")
local WEBHOOK = "https://discord.com/api/webhooks/..."   -- your webhook URL

local function discord(text)
  local body = '{"content":"' .. text:gsub('\\', '\\\\'):gsub('"', '\\"') .. '"}'
  local ok, err = pcall(function()
    for _ in internet.request(WEBHOOK, body, {["Content-Type"] = "application/json"}) do end
  end)
  if not ok then print("Discord message failed: " .. tostring(err)) end
end

discord("EBF needs maintenance")
```
Call `discord(...)` from the alarm program instead of (or as well as) beeping, but only when something changes, not every 5 seconds.
