# Reading GregTech machines with OpenComputers (GTNH)

## Connecting a GregTech machine
Put an OC Adapter against any GregTech machine or multiblock controller (for a multiblock, the controller block), and cable the adapter to the computer. The machine appears as component type `gt_machine`. Energy storage blocks (battery buffers, transformers) also give `gt_energyContainer`, and a Lapotronic Supercapacitor controller gives `LSC`. Several machines: one adapter per machine (an adapter touches up to 6 blocks), then loop over `component.list("gt_machine")`.

## gt_machine methods (exact names)
- `getName()` -> machine name; `getCoordinates()` -> `{x, y, z}`; `getOwnerName()`
- `isMachineActive()` -> true while it is running a recipe
- `hasWork()` -> true if it has something to do
- `isWorkAllowed()` / `setWorkAllowed(true|false)` -> read or flip the machine's on/off switch (like the soft mallet)
- `getWorkProgress()`, `getWorkMaxProgress()` -> progress in ticks (percent = progress / max * 100; max is 0 when idle)
- `getSensorInformation()` -> table of text lines, the same info as the GregTech scanner (problems, efficiency, heat, parallel, EU/t)
- Energy: `getEUStored()`, `getStoredEU()`, `getEUMaxStored()`, `getEUCapacity()`, `getStoredEUString()`, `getEUCapacityString()`, `getInputVoltage()`, `getOutputVoltage()`, `getOutputAmperage()`, `getEUInputAverage()`, `getEUOutputAverage()`, `getAverageElectricInput()`, `getAverageElectricOutput()`
- Steam: `getSteamStored()`, `getStoredSteam()`, `getSteamCapacity()`, `getSteamMaxStored()`

## Reading the sensor lines
`getSensorInformation()` returns lines with Minecraft colour codes (`§a`, `§r`). Clean them before matching:
```lua
local function sensor(machine)
  local lines = {}
  for _, line in ipairs(machine.getSensorInformation()) do
    lines[#lines + 1] = (line:gsub("§.", ""))
  end
  return lines
end
local function problems(machine)          -- multiblocks: maintenance problems, 0 = fine
  for _, line in ipairs(sensor(machine)) do
    local n = line:match("Problems:%s*(%d+)")
    if n then return tonumber(n) end
  end
  return 0
end
```
The exact wording differs between machines; print the lines once to see what yours shows before matching on them.

## Telling why a machine stopped
- `isWorkAllowed()` is false: someone turned it off (soft mallet or `setWorkAllowed(false)`).
- `problems(machine) > 0`: the multiblock needs maintenance (fix with tools or an auto-maintenance hatch).
- `hasWork()` true but `isMachineActive()` false for a while: it wants to run but can't, usually not enough power, output full, or missing coils/heat.
- `hasWork()` false: nothing to do, out of inputs. Normal for most machines most of the time, so only alarm on this for machines that should always run (power generators).

## Energy storage and the LSC
Battery buffers and similar: component `gt_energyContainer` with `getStoredEU()`, `getEUCapacity()`, `getStoredEUString()`, `getEUCapacityString()`, `getInputVoltage()`, `getOutputVoltage()`, `getOutputAmperage()`, `getAverageElectricInput()`, `getAverageElectricOutput()`, `getStoredSteam()`, `getSteamCapacity()`.
Lapotronic Supercapacitor (LSC) controller: component `LSC` with `getStoredEU()`, `getEUCapacity()`, `getStoredEUString()`, `getEUCapacityString()`. The LSC can hold more EU than a Lua number shows exactly, so for big ones read the String versions and convert for display. Its `gt_machine` sensor lines show average input and output per tick.

## Power percentage and time left
```lua
local lsc = component.LSC
local stored, capacity = lsc.getStoredEU(), lsc.getEUCapacity()
local percent = capacity > 0 and stored / capacity * 100 or 0
-- rate: measure twice, 20 seconds apart (400 ticks)
local before = lsc.getStoredEU(); os.sleep(20); local after = lsc.getStoredEU()
local perTick = (after - before) / 400
if perTick < 0 then print(string.format("%.0f minutes left", stored / -perTick / 20 / 60)) end
```

## Turning machines off when power is low
`setWorkAllowed(false)` pauses a machine exactly like a soft mallet. A common GTNH program checks the LSC or battery buffer every few seconds and pauses big consumers (an EBF array, a fusion reactor) below 20% power, then resumes them above 50%. Use two thresholds like this so machines don't flick on and off.
