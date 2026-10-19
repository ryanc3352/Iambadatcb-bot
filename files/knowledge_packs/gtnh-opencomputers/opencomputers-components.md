# OpenComputers components (exact method names)

## Sides
Many methods take a side number from `local sides = require("sides")`: `sides.bottom` (0), `sides.top` (1), `sides.north` (2), `sides.south` (3), `sides.west` (4), `sides.east` (5). The transposer and the Redstone I/O block use these compass sides. A redstone card inside a computer case counts sides relative to the case: `sides.front`, `sides.back`, `sides.left`, `sides.right`, `sides.top`, `sides.bottom` (the front is where the case faces).

## Redstone (redstone card or Redstone I/O block)
Component type `redstone`:
- `getInput(side)` -> strength 0-15 coming in on that side; `getInput()` -> table of all sides.
- `getOutput(side)`, `setOutput(side, value)` -> sets 0-15 on a side, returns the old value. `setOutput({[sides.top]=15})` sets several.
- `getComparatorInput(side)`.
- Bundled cables (tier 2 card): `getBundledInput(side, color)`, `setBundledOutput(side, color, value)`, colours from `require("colors")` (`colors.white` is 0).
- Wireless (tier 2 card): `setWirelessFrequency(n)`, `setWirelessOutput(true)`, `getWirelessInput()`.
A redstone signal event `redstone_changed` fires when an input changes: `event.pull("redstone_changed")`.

## Transposer (move items and fluids between blocks)
Component type `transposer`. It touches inventories on its six sides:
- `getInventorySize(side)`, `getInventoryName(side)`
- `getStackInSlot(side, slot)` -> table `{name, label, size, maxSize, damage, ...}` or nil
- `getSlotStackSize(side, slot)`, `getSlotMaxStackSize(side, slot)`
- `transferItem(sourceSide, sinkSide, count, sourceSlot, sinkSlot)` -> number moved (slots optional)
- `getAllStacks(side)` -> iterator; `.getAll()` gives every stack at once
- `transferFluid(sourceSide, sinkSide, count)` (mB), `getTankCount(side)`, `getFluidInTank(side, tank)`, `getTankLevel(side, tank)`, `getTankCapacity(side, tank)`
Slots start at 1. No upgrade is needed: the transposer is its own block, connected to the computer by cable.

## Inventory controller (read a chest through an adapter or robot)
With an Inventory Controller Upgrade in an adapter, component type `inventory_controller`:
`getInventorySize(side)`, `getStackInSlot(side, slot)`, `getAllStacks(side)`. It reads; to move items between chests use a transposer.

## Internet card (HTTP)
```lua
local internet = require("internet")
local body = ""
for chunk in internet.request("https://example.com/api", nil, {["User-Agent"]="OC"}) do
  body = body .. chunk
end
-- POST: internet.request(url, "text to send", {["Content-Type"]="application/json"})
```
`internet.request(url, postData, headers)` returns an iterator of text chunks; wrap it in `pcall` because it errors when the site can't be reached. OpenOS has no JSON library: download one (for example `json.lua` by rxi) with `wget`, or build simple JSON strings by hand. By default OC blocks requests to local addresses (127.0.0.1, 192.168.x.x, 10.x.x.x), so a web server on the same PC must be reached through its public address. Discord webhooks work: POST `{"content":"text"}` as JSON to the webhook URL.

## GPU and screen (method list)
Component type `gpu`: `set(x, y, text)`, `get(x, y)`, `fill(x, y, width, height, char)`, `copy(x, y, w, h, dx, dy)`, `setForeground(0xRRGGBB)`, `setBackground(0xRRGGBB)`, `getResolution()`, `setResolution(w, h)`, `maxResolution()`, `bind(screenAddress)`. Screen sizes: tier 1 50x16, tier 2 80x25, tier 3 160x50. Several screen blocks placed together make one bigger screen.

## Modem and other computers
Network card, component type `modem`: `open(port)`, `send(address, port, ...)`, `broadcast(port, ...)`. Messages arrive as the event `modem_message` with `(_, localAddress, from, port, distance, ...)`. A wireless network card reaches other computers without cables (range depends on tier).

## Computer API
`local computer = require("computer")`: `computer.uptime()` seconds since start, `computer.freeMemory()`, `computer.totalMemory()`, `computer.energy()` / `computer.maxEnergy()` (OC energy in the computer), `computer.beep(freq, seconds)`, `computer.shutdown(true)` reboots. `os.time()` is in-game time; use `computer.uptime()` to measure real seconds.
