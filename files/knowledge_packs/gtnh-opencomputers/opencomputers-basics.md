# OpenComputers basics (GTNH)

## What OpenComputers is
OpenComputers (OC) adds computers you program in Lua inside Minecraft. In GT New Horizons the computers run OpenOS and Lua 5.3. Programs talk to blocks through "components": a GPU, a screen, a redstone card, an adapter next to a machine, and so on. Everything a program can do goes through `require("component")`. There is no access to files on the real PC, only the computer's own disk.

## Building a working computer
A computer needs: a Computer Case, a CPU, at least one RAM stick, a hard disk (or floppy), a Graphics Card, a Screen and a Keyboard (placed against the screen), plus an EEPROM with the Lua BIOS. Power it (OC converts EU from GregTech cables, or use a Power Converter). Put the OpenOS floppy in a disk drive, start the computer, and run `install` to copy OpenOS to the hard disk. Higher tiers (tier 2 and 3 parts) give more memory, more components and a bigger screen.

## Using the shell
OpenOS has a Unix-like shell. Useful commands: `ls`, `cd`, `edit file.lua` (a text editor: Ctrl+S saves, Ctrl+W quits), `lua` (an interactive Lua prompt), `components` (lists connected components with their addresses), `reboot`. Run a program by typing its name, e.g. `monitor` runs `monitor.lua` from the current folder or /home. Ctrl+Alt+C stops a running program. With an internet card: `wget -f URL file.lua` downloads a file and `pastebin get CODE file.lua` fetches from pastebin.

## Running a program when the computer starts
Put the command on its own line in `/home/.shrc` (for example a line `monitor`); OpenOS runs that file when the shell starts. Make sure the program can survive errors: wrap the main loop in `pcall` or restart it, otherwise one error stops it until someone reboots the computer.

## Components: finding and calling them
```lua
local component = require("component")
for address, kind in component.list() do print(kind, address) end   -- everything connected
local gpu = component.gpu                         -- the primary component of a type
local m = component.proxy(component.list("gt_machine")()) -- the first gt_machine
for address in component.list("gt_machine") do    -- all of them
  local machine = component.proxy(address)
  print(machine.getName())
end
```
`component.<type>` only works for the primary one of that type. With several machines, loop over `component.list(type)` and use `component.proxy(address)`. `component.methods(address)` lists what a component can do; the `components` shell command prints addresses. Short addresses work in the shell: `component.get("3f2a")`.

## The Adapter block
Most mod blocks (GregTech machines, AE2 parts, energy storage) become components through an **Adapter**: place the adapter touching the block, and connect the adapter to the computer with OC cables (or place it next to the case). One adapter can touch up to 6 blocks. The block then shows up in `component.list()` under its type, e.g. `gt_machine`, `LSC`, `me_interface`. Some things need an upgrade in the adapter (e.g. an Inventory Controller Upgrade to read a chest).

## Waiting, timers and events
```lua
local event = require("event")
os.sleep(5)                                   -- wait 5 seconds (lets the server run; always sleep in loops)
local name, _, char, code = event.pull(10, "key_down")  -- wait up to 10 s for a key
local id = event.timer(60, function() print("a minute") end, math.huge)  -- repeat every 60 s
event.cancel(id)
```
A loop without `os.sleep` or `event.pull` freezes the computer and is stopped with "too long without yielding". In GTNH keep checks to every few seconds; polling every tick wastes server time.

## Screen and text output
```lua
local term = require("term")
local gpu = require("component").gpu
term.clear()
gpu.setResolution(80, 25)            -- tier 2 screen max 80x25, tier 3 max 160x50
gpu.setForeground(0x00FF00)          -- colours are 0xRRGGBB
gpu.set(1, 1, "Power: OK")           -- write at column 1, row 1
gpu.fill(1, 2, 80, 1, " ")           -- clear a row
gpu.setForeground(0xFFFFFF)
```
`print` and `io.write` write at the cursor; `gpu.set` writes at an exact place without scrolling, which is better for dashboards.

## Beeps and sounds
`require("computer").beep(frequency, seconds)` plays a tone from the computer case (frequency 20 to 2000 Hz), e.g. `computer.beep(1000, 0.3)`. It is only heard near the computer. For a base-wide alarm, set a redstone output (redstone card or Redstone I/O block) that powers note blocks or an alarm block, or send a message to Discord with the internet card.

## Lua reminders for OC programs
Lua 5.3: `local` for variables, `..` joins strings, `#t` is a table's length, tables start at index 1, `~=` means not equal. `string.format("%.1f%%", 12.34)` formats numbers. `tostring(x)` before joining numbers in old code. Big EU numbers can exceed what a Lua number shows exactly; use the `...String` methods (e.g. `getStoredEUString`) for huge storage like an LSC. GregTech sensor text has colour codes like `§a`: remove them with `line:gsub("§.", "")`.
