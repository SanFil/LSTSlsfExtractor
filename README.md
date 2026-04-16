# LSTS LSF Extractor

Decode and convert [DUNE](https://github.com/lsts/dune) / [IMC](https://www.lsts.pt/docs/imc/) binary mission logs (LSF files) to CSV — without Neptus or MRA.

---

## What is this?

[DUNE: Unified Navigation Environment](https://github.com/lsts/dune) is the on-board software framework used by LSTS unmanned vehicles (AUVs, USVs, UAVs). During operation it produces binary mission logs in **LSF** (LSTS Serialized Format) containing serialized **IMC** (Inter-Module Communication) messages — navigation state, GPS fixes, attitude, sensor readings, actuator commands, plan execution, and more.

These logs are typically analysed using [Neptus/MRA](https://github.com/LSTS/neptus), a heavyweight Java application. This project provides a lightweight, **pure-Python** alternative that:

- Decodes all 370+ IMC message types directly from the binary format
- Exports to CSV for analysis in Python/pandas, MATLAB, R, Excel, or any tool you prefer
- Includes an **interactive terminal UI** for browsing and exploring logs visually

**Zero external dependencies** — runs on any system with Python 3.10+.

---

## Repository Structure

```
LSTSlsfExtractor/
├── lsf2csv.py       # Command-line converter: LSF → CSV
├── lsf_tui.py       # Interactive terminal UI for browsing logs
├── imc_parser.py    # IMC.xml message definition parser
├── lsf_reader.py    # Binary LSF packet reader / deserializer
├── logs/            # Drop your DUNE log folders here (git-ignored)
│   └── .gitkeep
├── README.md
└── .gitignore
```

| Module | Purpose |
|--------|---------|
| `imc_parser.py` | Parses `IMC.xml` into a dictionary of message definitions with field types, enums, and bitfields |
| `lsf_reader.py` | Reads `.lsf` / `.lsf.gz` files, decodes 20-byte IMC headers, deserialises payloads for all field types (fixed scalars, `plaintext`, `rawdata`, inline `message`, `message-list`) |
| `lsf2csv.py` | CLI tool — list message types, export to CSV, batch-process directories |
| `lsf_tui.py` | Curses-based terminal UI — browse files, inspect message summaries, view data tables, drill into individual messages, export interactively |

---

## Quick Start

### 1. List all message types in a log

```bash
python3 lsf2csv.py /path/to/Data.lsf.gz --list
```

Example output:

```
Message Type                             Count
-----------------------------------------------
  ServoPosition                         499924
  EulerAngles                           126231
  SimulatedState                        124981
  AngularVelocity                       124981
  Acceleration                          124981
  CpuUsage                               50267
  EntityState                            44020
  Rpm                                    24996
  Distance                               12498
  VehicleState                            5000
  ManeuverControlState                    4815
  GpsFix                                  1251
  EstimatedState                          1250
  ...
-----------------------------------------------
  TOTAL                                1158679

  33 distinct message types found.
```

### 2. Export specific message types

```bash
python3 lsf2csv.py /path/to/Data.lsf.gz -m EstimatedState -m GpsFix
```

This creates one CSV per message type in the same directory as the LSF file:
- `Data_EstimatedState.csv`
- `Data_GpsFix.csv`

### 3. Export with all the bells and whistles

```bash
python3 lsf2csv.py /path/to/Data.lsf.gz \
    -m EstimatedState -m GpsFix \
    --human-time \
    --degrees \
    --resolve-entities \
    -o ./output/
```

This produces CSVs with:
- **Human-readable UTC timestamps** (`2025-03-25 15:22:26.150` instead of `1742916146.150906`)
- **Lat/lon in degrees** (`63.626` instead of `1.110` radians)
- **Entity names** resolved from `EntityInfo` messages in the log (e.g., `Navigation`, `SimulatedGPS`, `Simulation Engine`)

Sample output:

```
timestamp                    | src   | src_ent | src_ent_name | lat       | lon      | psi    | u      | ...
2025-03-25 15:22:26.150      | 34819 | 39      | Navigation   | 63.626178 | 9.477919 | 1.2915 | 2.3335 | ...
2025-03-25 15:22:27.150      | 34819 | 39      | Navigation   | 63.626182 | 9.477956 | 1.2894 | 1.6090 | ...
2025-03-25 15:22:28.150      | 34819 | 39      | Navigation   | 63.626186 | 9.477983 | 1.2901 | 1.1899 | ...
```

---

## CLI Reference

```
usage: lsf2csv.py [-h] [-m MSG] [--all] [--list] [-o OUTPUT] [--imc IMC]
                   [--merge] [--human-time] [--resolve-entities] [--degrees]
                   [--batch]
                   lsf_file
```

### Positional argument

| Argument | Description |
|----------|-------------|
| `lsf_file` | Path to a `.lsf` or `.lsf.gz` file, or a directory when using `--batch` |

### Options

| Flag | Description |
|------|-------------|
| `-m MSG`, `--message MSG` | Message type abbreviation to export. Repeatable: `-m EstimatedState -m GpsFix -m EulerAngles` |
| `--all` | Export all message types found in the log (one CSV per type) |
| `--list` | Print a summary of message types and counts, then exit |
| `-o DIR`, `--output DIR` | Output directory for CSV files (default: same directory as the LSF file) |
| `--imc PATH` | Path to `IMC.xml` definitions file (auto-detected if not specified) |
| `--merge` | Merge all selected message types into a single CSV file, sorted by timestamp |
| `--human-time` | Write timestamps as `YYYY-MM-DD HH:MM:SS.mmm` (UTC) instead of Unix epoch |
| `--resolve-entities` | Add `src_ent_name` and `dst_ent_name` columns with human-readable entity labels |
| `--degrees` | Convert `lat` and `lon` fields from radians to degrees |
| `--batch` | Recursively find and process all LSF files under the given directory |

### Usage examples

```bash
# List what's in a single log session
python3 lsf2csv.py logs/20250325/142323/Data.lsf.gz --list

# Export navigation + GPS from one session
python3 lsf2csv.py logs/20250325/142323/Data.lsf.gz -m EstimatedState -m GpsFix

# Full-featured export
python3 lsf2csv.py logs/20250325/152225/Data.lsf.gz \
    -m EstimatedState -m GpsFix -m EulerAngles \
    --human-time --degrees --resolve-entities -o ./csv_output/

# Merge attitude + nav into one time-sorted CSV
python3 lsf2csv.py logs/20250325/152225/Data.lsf.gz \
    -m EstimatedState -m EulerAngles --merge

# Export everything from a session
python3 lsf2csv.py logs/20250325/152225/Data.lsf.gz \
    --all --human-time --degrees -o ./all_csv/

# Batch-process ALL sessions in an entire day
python3 lsf2csv.py logs/20250325/ --batch -m EstimatedState -m GpsFix

# Batch-process ALL days and ALL sessions in logs/
python3 lsf2csv.py logs/ --batch -m EstimatedState --human-time --degrees

# Use a specific IMC.xml version
python3 lsf2csv.py logs/20250325/142323/Data.lsf.gz \
    -m GpsFix --imc /path/to/dune/imc/IMC.xml
```

---

## Interactive Terminal UI

The TUI defaults to browsing the `logs/` directory. Just drop your log folders there and run:

```bash
python3 lsf_tui.py
```

Or point it at a different location:

```bash
python3 lsf_tui.py /path/to/dune/build/log/ntnu-autonaut/
python3 lsf_tui.py /path/to/Data.lsf.gz
```

### Screens

**1. Session Browser** — Recursively discovers all LSF files and displays them grouped by date. Each date folder (`YYYYMMDD`) is shown as a section header with formatted dates, and sessions within are listed by time (`HH:MM:SS`) with any suffix (e.g., `[cmd-ntnu-autonaut]`, `[whatever_mission]`) and file size. This means you can load entire days — even multiple days — and navigate them cleanly.

Example of what the browser looks like:

```
  ┌─ 2025-03-25  (32 sessions)
  │ ▸ 14:23:23                             6.1 MB
  │   14:31:27  [cmd-ntnu-autonaut]        7.2 MB
  │   14:39:28                           177.1 KB
  │   14:39:41  [cmd-ntnu-autonaut]        7.4 MB
  │   ...
  │   15:22:25                            17.0 MB

  ┌─ 2025-03-26  (5 sessions)
  │   08:06:04                             2.2 MB
  │   08:23:10  [whatever_mission]            12.5 MB
```

**2. Message Summary** — Shows all message types in the selected log with their counts and IMC categories. The header shows the formatted date and session time. Select types with `Space`, toggle all with `a`.

**3. Data Table** — Scrollable table of decoded messages. Scroll rows with arrow keys, pan columns with left/right. Lat/lon auto-converted to degrees, entity IDs resolved to names.

**4. Detail View** — Press `d` on any row to see a vertical field-by-field view of that single message, useful for messages with many fields.

**5. CSV Export** — Press `e` to export selected message types (or current type if none selected) to `csv_export/` next to the LSF file.

### Keyboard controls

| Key | Action |
|-----|--------|
| `Up` / `Down` | Navigate rows |
| `Left` / `Right` | Scroll columns (data table) |
| `PgUp` / `PgDn` | Page through data |
| `Home` / `End` | Jump to first / last item |
| `Space` | Toggle selection (message summary) |
| `a` | Select all / deselect all |
| `Enter` | Open file / view message data |
| `d` | Detail view of current message |
| `e` | Export selected types to CSV |
| `b` | Go back to previous screen |
| `q` or `Esc` | Quit |

---

## IMC.xml — Message Definitions

The tool needs an `IMC.xml` file that describes the binary layout of each IMC message type. This file is part of every DUNE source tree.

### Auto-detection

The tool searches these paths automatically (in order):

1. `../dune-software/NEW/imc/IMC.xml` (relative to this repo)
2. `../dune-software/NTNU/imc/IMC.xml`
3. `../dune-software/imc/IMC.xml`

### Manual override

```bash
python3 lsf2csv.py logs/Data.lsf.gz --imc /path/to/your/IMC.xml -m EstimatedState
```

### IMC version compatibility

Different DUNE versions may ship different `IMC.xml` files with different message IDs or field layouts. For best results, use the `IMC.xml` that matches the DUNE version that generated the log. The version can be checked:

```bash
head -15 /path/to/IMC.xml | grep version
# e.g.: version="5.4.30"
```

---

## Loading Logs into `logs/`

**You can drop an entire day (or multiple days) of DUNE logs into `logs/` and both the CLI and the TUI will handle it automatically.**

DUNE organises logs under `build/log/<vehicle>/<date>/<time>/`:

```
build/log/ntnu-autonaut/
├── 20250325/                             ← date folder (YYYYMMDD)
│   ├── 142323/                           ← session folder (HHMMSS)
│   │   ├── Data.lsf.gz                  ← compressed mission log
│   │   ├── Config.ini                    ← DUNE config snapshot
│   │   └── Output.txt                    ← console output
│   ├── 143127_cmd-ntnu-autonaut/         ← session with suffix
│   │   └── Data.lsf.gz
│   ├── 145620/
│   │   └── Data.lsf.gz
│   └── ...  (dozens of sessions per day)
└── 20250326/
    ├── 080604/
    │   └── Data.lsf.gz
    ├── 082310_whatever_mission/
    │   └── Data.lsf.gz
    └── ...
```

### How to load logs

Simply copy or symlink the **date folders** into `logs/`:

```bash
# Copy an entire day of logs
cp -r /path/to/dune/build/log/ntnu-autonaut/20250325/ logs/

# Copy multiple days at once
cp -r /path/to/dune/build/log/ntnu-autonaut/2025032*/ logs/

# Or symlink to avoid duplicating data
ln -s /path/to/dune/build/log/ntnu-autonaut/20250325/ logs/20250325
```

The resulting `logs/` directory will look like this:

```
logs/
├── 20250325/
│   ├── 142323/Data.lsf.gz
│   ├── 143127_cmd-ntnu-autonaut/Data.lsf.gz
│   ├── 145620/Data.lsf.gz
│   └── ... (32 sessions)
├── 20250326/
│   ├── 080604/Data.lsf.gz
│   ├── 082310_whatever_mission/Data.lsf.gz
│   └── ... (5 sessions)
└── .gitkeep
```

All contents of `logs/` are git-ignored — only the empty directory is tracked. You can load as many days and sessions as you need without affecting the repository.

---

## LSF Binary Format Reference

An LSF file contains no file-level header. It is a raw concatenation of IMC packets:

```
┌──────────┬─────────┬────────┐ ┌──────────┬─────────┬────────┐
│ Header   │ Payload │ CRC    │ │ Header   │ Payload │ CRC    │  ...
│ 20 bytes │ N bytes │ 2 bytes│ │ 20 bytes │ N bytes │ 2 bytes│
└──────────┴─────────┴────────┘ └──────────┴─────────┴────────┘
```

Files are often gzip-compressed (`.lsf.gz`). The tool handles both transparently.

### Packet header (20 bytes)

All multi-byte fields are **little-endian** when `sync == 0xFE54`, or big-endian when `sync == 0x54FE`.

| Offset | Size | Type | Field | Description |
|--------|------|------|-------|-------------|
| 0 | 2 | `uint16` | `sync` | Sync word: `0xFE54` (LE) or `0x54FE` (BE) |
| 2 | 2 | `uint16` | `mgid` | Message ID (matches `id` attribute in `IMC.xml`) |
| 4 | 2 | `uint16` | `size` | Payload length in bytes (not including header or footer) |
| 6 | 8 | `fp64` | `timestamp` | Unix epoch seconds (UTC), IEEE 754 double |
| 14 | 2 | `uint16` | `src` | Source IMC address |
| 16 | 1 | `uint8` | `src_ent` | Source entity ID |
| 17 | 2 | `uint16` | `dst` | Destination IMC address |
| 19 | 1 | `uint8` | `dst_ent` | Destination entity ID |

### Packet footer (2 bytes)

| Offset | Size | Type | Field | Description |
|--------|------|------|-------|-------------|
| 20+N | 2 | `uint16` | `crc16` | CRC-16-IBM over header + payload (polynomial `0x8005`) |

### Payload field types

| IMC type | Wire format |
|----------|-------------|
| `int8_t`, `uint8_t` | 1 byte |
| `int16_t`, `uint16_t` | 2 bytes |
| `int32_t`, `uint32_t` | 4 bytes |
| `int64_t` | 8 bytes |
| `fp32_t` | 4 bytes (IEEE 754 float) |
| `fp64_t` | 8 bytes (IEEE 754 double) |
| `plaintext` | `uint16` length + UTF-8 bytes |
| `rawdata` | `uint16` length + raw bytes |
| `message` | `uint16` message ID + serialised payload (`0xFFFF` = null) |
| `message-list` | `uint16` count + N inline messages |

### Common message types

| Message | ID | Key fields | Description |
|---------|----|------------|-------------|
| `EstimatedState` | 350 | lat, lon, height, phi, theta, psi, u, v, w, depth, alt | Fused navigation state |
| `GpsFix` | 253 | lat, lon, height, satellites, cog, sog, hdop | Raw GPS fix |
| `EulerAngles` | 254 | phi, theta, psi, psi_magnetic | Attitude (roll, pitch, yaw) |
| `Acceleration` | 257 | x, y, z | Body-frame accelerations |
| `AngularVelocity` | 256 | x, y, z | Body-frame angular rates |
| `SimulatedState` | 50 | lat, lon, height, phi, theta, psi, u, v, w | Simulated vehicle state |
| `ServoPosition` | 281 | id, value | Servo/actuator positions |
| `Rpm` | 250 | value | Motor RPM |
| `Distance` | 262 | value | Range sensor |
| `VehicleState` | 500 | op_mode, error_count, maneuver_type | Vehicle operational state |
| `PlanControlState` | 560 | state, plan_id, man_id | Plan execution status |
| `EntityInfo` | 3 | id, label, component | Entity ID → name mapping |
| `EntityState` | 1 | state, flags, description | Entity health status |
| `LoggingControl` | 188 | op, name | Log start/stop events |

---

## Using Exported CSVs

### Python / pandas

```python
import pandas as pd

df = pd.read_csv("Data_EstimatedState.csv")
print(df[["timestamp", "lat", "lon", "psi", "u"]].head())

# Plot vehicle track
import matplotlib.pyplot as plt
plt.plot(df["lon"], df["lat"])
plt.xlabel("Longitude (deg)")
plt.ylabel("Latitude (deg)")
plt.title("Vehicle Track")
plt.axis("equal")
plt.show()
```

### MATLAB

```matlab
T = readtable('Data_EstimatedState.csv');
plot(T.lon, T.lat);
xlabel('Longitude (deg)');
ylabel('Latitude (deg)');
title('Vehicle Track');
axis equal;
```

---

## Performance

Tested on real mission logs from an NTNU Autonaut USV:

| Log size (gzipped) | Messages | Parse time | Message types |
|---------------------|----------|------------|---------------|
| 22 KB | 1,551 | 0.1s | 37 |
| 7.6 MB | ~300,000 | ~1.0s | 33 |
| 17.8 MB | 1,158,679 | ~3.0s | 33 |

Filtering with `-m` skips deserialization of unwanted types, making targeted exports even faster.

---

## Requirements

- **Python 3.10+** (uses `match`-free syntax, `dataclasses`, `typing`, `pathlib`)
- **No external packages** — everything uses the Python standard library (`struct`, `gzip`, `csv`, `xml.etree`, `curses`, `argparse`)

---

## Contributing

1. Fork the repo
2. Create a feature branch
3. Test against real LSF files
4. Submit a pull request

---

## Acknowledgements

- [LSTS](https://www.lsts.pt/) — Laboratório de Sistemas e Tecnologia Subaquática, University of Porto
- [DUNE](https://github.com/lsts/dune) — Unified Navigation Environment
- [IMC](https://www.lsts.pt/docs/imc/) — Inter-Module Communication protocol
- [Neptus](https://github.com/LSTS/neptus) — Command and Control software

---

## License

MIT
