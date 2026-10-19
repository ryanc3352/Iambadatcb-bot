# AE2 (Applied Energistics) with OpenComputers in GTNH

## Connecting to the ME system
Put an OC Adapter against an ME Controller (component `me_controller`) or an ME Interface (component `me_interface`), or place an ME Interface next to the computer. Both give the whole network's contents. The adapter needs no upgrade. In GTNH the dual interface and the level maintainer are components too (`me_interface`, `level_maintainer`).

## Network methods (me_controller and me_interface)
- `getItemsInNetwork([filter])` -> list of item tables
- `getFluidsInNetwork()` -> list of fluid tables
- `getCraftables([filter])` -> list of craftable objects (patterns the system knows)
- `getCpus()` -> list of crafting CPUs (`name`, `storage`, `coprocessors`, `busy`)
- `store(filter, dbAddress[, startSlot, count])` -> copy matching item types into a database component
- Power: `getStoredPower()`, `getMaxStoredPower()`, `getAvgPowerUsage()`, `getAvgPowerInjection()`, `getIdlePowerUsage()` (AE units)

## Item tables and filters
An item table looks like `{name="minecraft:iron_ingot", damage=0, label="Iron Ingot", size=1234, maxSize=64, hasTag=false, isCraftable=true}`. `size` is how many are stored. A filter is a table of fields that must match:
```lua
local me = require("component").me_interface
local found = me.getItemsInNetwork({label = "Steel Ingot"})
local count = found[1] and found[1].size or 0
-- GregTech items share names (gregtech:gt.metaitem.01); match on label, or name plus damage:
local motors = me.getItemsInNetwork({name = "gregtech:gt.metaitem.01", damage = 32600})
```
Calling `getItemsInNetwork()` without a filter on a big system returns thousands of items and is slow: always filter.

## Requesting a craft
```lua
local craftables = me.getCraftables({label = "Steel Plate"})
if craftables[1] then
  local status = craftables[1].request(64)       -- amount; returns a status object
  while not status.isDone() and not status.isCanceled() do os.sleep(2) end
  print(status.isDone() and "crafted" or "cancelled (missing items?)")
end
```
`craftable.request(amount[, prioritizePower[, cpuName]])` starts a crafting job like clicking Craft in the terminal; `craftable.getItemStack()` shows what it makes. Check `getCpus()` for a free CPU before requesting many jobs.

## Keeping items in stock (stock keeper)
The classic program: a list of `{label, keep, batch}`; every 30 seconds read each item's count with a filter; if below `keep` and nothing is already crafting it, request `batch` more. Remember jobs you started (store the status objects) so you don't request the same item twice while it's crafting. In GTNH the Level Maintainer block does this without a program; OC is useful for conditions the maintainer can't do (only craft when the LSC is above 50%, only at night, post to Discord).

## ME interface configuration and the database
`me_interface.getInterfaceConfiguration(slot)` / `setInterfaceConfiguration(slot, dbAddress, dbIndex, count)` read or set what the interface keeps stocked in a slot. Item types for these calls come from a **database** component (Database Upgrade in an adapter): fill it with `me.store({label="..."}, db.address, 1)` and then refer to `db.address` and the index. Fluid interfaces: `getFluidInterfaceConfiguration(side)`, `setFluidInterfaceConfiguration(side, dbAddress, dbIndex)`.

## Level maintainer component (GTNH)
`level_maintainer.getSlot(slot)`, `setSlot(slot, dbAddress, dbIndex, quantity, batchSize)` (or `setSlot(slot, quantity, batchSize)` to change amounts), `isEnable(slot)`, `isDone(slot)`, `active()`. Lets a program change what the level maintainer keeps stocked, e.g. raise targets when power is plentiful.
