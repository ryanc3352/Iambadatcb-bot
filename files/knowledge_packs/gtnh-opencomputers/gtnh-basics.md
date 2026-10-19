# GT New Horizons basics for answering questions

## Voltage tiers
GregTech energy is EU, sent in packets of a voltage (EU per packet) and amperage (packets per tick). Tiers and their voltage: ULV 8, LV 32, MV 128, HV 512, EV 2,048, IV 8,192, LuV 32,768, ZPM 131,072, UV 524,288, UHV 2,097,152, UEV 8,388,608, UIV 33,554,432, UMV 134,217,728, UXV 536,870,912, MAX 2,147,483,640. Each tier is 4x the previous. A machine fed a higher voltage than its tier explodes; use a transformer to step voltage down.

## Amps, cables and loss
A cable has a maximum voltage and amperage. Too high a voltage burns the cable; more amps than it carries also burns it. Every block of cable loses some EU per amp (less with better materials; superconductors lose none). A multiblock pulls its power through its energy hatches (each hatch has a tier and amperage). Keep cable runs short at low tiers and use a transformer close to the machines.

## Overclocking
A machine of a higher tier than the recipe needs runs it faster: each tier above the recipe's tier makes it 2x faster for 4x the EU per tick (more total energy, same items). Some multiblocks (and the EBF with spare coil heat) get "perfect" overclocks: 4x faster for 4x EU per tick. Recipes have a minimum tier: an MV recipe needs at least an MV machine.

## Multiblocks and maintenance
Multiblocks are built from casings around a controller; the controller's tooltip or NEI preview shows the shape (in GTNH the controller often shows a hologram with a Blueprint). Most need a maintenance hatch: problems appear over time and the machine slows or stops until fixed with the right tools (wrench, screwdriver, soft mallet, hammer, soldering iron, crowbar) or an auto-maintenance hatch. Polluting multiblocks (and steam machines) need a muffler hatch; pollution spreads through chunks and harms the area.

## Electric Blast Furnace and coils
The EBF needs heat from its coils for hotter recipes: Cupronickel 1,801 K, Kanthal 2,701 K, Nichrome 3,601 K, TPV 4,501 K, HSS-G 5,401 K, HSS-S 6,301 K, Naquadah 7,201 K, Naquadah Alloy 8,101 K, Trinium 9,001 K, Electrum Flux 9,901 K, Awakened Draconium 10,801 K, Infinity 11,701 K, Hypogen 12,601 K, Eternal 13,501 K. Higher energy hatch tiers add 100 K per tier above MV. Spare heat helps: every 900 K above the recipe cuts the EU used by 5%, and every 1,800 K above allows a perfect overclock. Metals from the hotter EBF recipes come out as hot ingots that must be cooled in a vacuum freezer.

## Progression in short
Stone Age (no power, primitive furnaces, coke oven) -> Steam (steam machines, steel) -> LV (first electric machines, the Electric Blast Furnace for steel is the big MV-age goal) -> MV (chemical reactor, EBF, aluminium) -> HV (stainless steel; space travel starts around HV/EV) -> EV -> IV (platinum line, Assembly line later) -> LuV/ZPM/UV (fusion, wetware) -> UHV and beyond (endgame). The quest book (BetterQuesting) has a chapter per tier and is the best guide; main quests mark the path. The goal is the Stargate.

## Where to look things up in game
NEI (the item list on the right): press R on an item for recipes, U for uses. GregTech machines show tier, EU/t and time in NEI. The quest book explains each tier. A GregTech Portable Scanner (or OC's `getSensorInformation()`) shows a machine's status. The GTNH wiki (wiki.gtnewhorizons.com) has guides; recipes change between versions, so trust NEI for your version.
