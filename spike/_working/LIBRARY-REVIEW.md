# Library Re-pointing — Review

Regenerated against KiCad-Master-Lib `ed69332` (SparkFun `2423e36a`, OPL `b0035c51`).

**42 unresolved references remain.** Only references that fail to resolve today are listed.

Mark the `OK?` column `y` / `n` / write a correction.

`pins` = the count the BOARD embeds. Fingerprint matching cannot distinguish parts with
few pins — a 2-pin resistor looks identical to a 2-pin capacitor, and every 4-pin
connector looks alike. Those are separated out below.
---

## A. Distinctive parts — identity match, safe to accept  (1)

Pins/pads match a library part exactly, and the part has enough pins that a coincidental
collision is implausible.

| OK? | brd | kind | broken reference | proposed target | pins |
|-----|-----|------|------------------|-----------------|------|
|     | 1 | sym | `william_fets:PSMN1R0-30YLC,115` | `SparkFun-DiscreteSemi:Q_PMOS_9A_30V` | 5 |

## B. Generic (≤4 pins) or `*-rescue` — verify by eye  (23)

Fingerprint matching is unreliable here. The proposed target may well be wrong.
`*-rescue` entries are KiCad artefacts from a symbol going missing on project open;
most are plain stock parts (`Device:R`, `Device:C`, `power:GND`).

| OK? | brd | kind | broken reference | proposed target | pins |
|-----|-----|------|------------------|-----------------|------|
|     | 9 | sym | `SparkFun-Connector:I2C_01x04` | `SparkFun-Connector:Conn_01x04_JST_P1.0mm_Vertical_SMD` | 4 ⚠️ ambiguous |
|     | 4 | sym | `kml-custom:031-5431-1010` | `KMLib_Connectors:031-5431-1010_BNC_Coaxial_Right_Angle` | 4 |
|     | 3 | sym | `BREAD_Slice-rescue:GND-power` | `SparkFun-PowerSymbol:GND` | 1 |
|     | 2 | fp | `kml-custom:CONN4_2606-1104&slash_010-000_WAG` | `KMLib_Connectors:2606-1104_010-000_WAGO` | 4 |
|     | 2 | sym | `BREAD_Slice-rescue:Ferrite_Bead_Small-Device` | `KMLib_Connectors:1985195 PTSA Term Push Phoenix Contact` | 2 |
|     | 2 | sym | `kml-custom:DF2S6.8MFS_L3M` | `KMLib_Discrete_Semiconductors:CDBA140-G_Schottky_diode` | 2 ⚠️ ambiguous |
|     | 2 | sym | `BREAD_Slice-rescue:10uF_t-OCI_UPL_2_Capacitors-BREAD_Slice-rescue` | `KMLib_Connectors:1985195 PTSA Term Push Phoenix Contact` | 2 |
|     | 1 | sym | `BREAD_Slice-rescue:R_POT_US-Device` | `KMLib_Switches:1101M2S3CQE2` | 3 ⚠️ ambiguous |
|     | 1 | sym | `kml-custom:Term_PressFit_1x01_5mm_Phoenix_Contact_1751066` | `KMLib_Connectors:1751066_Term_PressFit_1x01_5mm_Phoenix_Contact` | 2 ⚠️ ambiguous |
|     | 1 | sym | `BREAD_Slice-rescue:10k_t-OCI_UPL_1_Resistors` | `KMLib_Switches:1101M2S3CQE2` | 3 ⚠️ ambiguous |
|     | 1 | sym | `BREAD_Slice-rescue:1K-OCI_UPL_1_Resistors` | `KMLib_Connectors:1985195 PTSA Term Push Phoenix Contact` | 2 |
|     | 1 | sym | `BREAD_Slice-rescue:1uF_t-OCI_UPL_2_Capacitors` | `KMLib_Connectors:1985195 PTSA Term Push Phoenix Contact` | 2 |
|     | 1 | sym | `BREAD_Slice-rescue:10uF_t-OCI_UPL_2_Capacitors` | `KMLib_Connectors:1985195 PTSA Term Push Phoenix Contact` | 2 |
|     | 1 | sym | `BREAD_Slice-rescue:Conn_01x03_Male-Connector` | `SparkFun-Connector:Conn_01x03_P2.54mm` | 3 ⚠️ ambiguous |
|     | 1 | fp | `KML-Custom:CONN_1217861-1_TEC` | `KMLib_Connectors:1217861-1_Tab` | 2 |
|     | 1 | sym | `Solar-Battery-Charger-rescue:CBC3225T100MRV-CBC3225T100MRV` | `KMLib_Connectors:1751066_Term_PressFit_1x01_5mm_Phoenix_Contact` | 2 ⚠️ ambiguous |
|     | 1 | sym | `Solar-Battery-Charger-rescue:Conn_01x02_Female-Connector` | `SparkFun-Connector:Barrier_Terminal_9.5mm-2` | 2 ⚠️ ambiguous |
|     | 1 | sym | `Solar-Battery-Charger-rescue:GND-power` | `SparkFun-PowerSymbol:GND` | 1 |
|     | 1 | sym | `Solar-Battery-Charger-rescue:WSLP1206R0200FEA-2020-04-21_06-00-44` | `KMLib_Connectors:1751066_Term_PressFit_1x01_5mm_Phoenix_Contact` | 2 ⚠️ ambiguous |
|     | 1 | sym | `kml-custom:CDBA140-G` | `KMLib_Discrete_Semiconductors:CDBA140-G_Schottky_diode` | 2 ⚠️ ambiguous |
|     | 1 | sym | `kml-custom:Tab_Amp_1217861-1` | `KMLib_Connectors:1217861-1_Tab` | 4 |
|     | 1 | sym | `kml-custom:PCC-SMP-V-K` | `KMLib_Connectors:PCC-SMP-V-K_Board_Thermocouple` | 4 |
|     | 1 | sym | `BREAD_Slice-rescue:Ferrite_Bead-Device` | `KMLib_Connectors:1985195 PTSA Term Push Phoenix Contact` | 2 |

## C. No match anywhere — recover into the library, or delete  (18)

No library part has these pins/pads. Either extract the geometry the board embeds back
into `kmlib-local`, or decide the reference is cruft.

| OK? | brd | kind | broken reference | proposed target | pins |
|-----|-----|------|------------------|-----------------|------|
|     | 5 | fp | `LOGO` | `—` | ? |
|     | 3 | fp | `KMLib_Boards_Modules:RaspberryPi_Pico_THT` | `—` | 40 |
|     | 2 | sym | `BREAD_Slice-rescue:+12V-power` | `—` | 1 |
|     | 1 | fp | `Arc` | `—` | ? |
|     | 1 | sym | `LTC4311:LTC4311ISC6-TRMPBF` | `—` | 6 |
|     | 1 | sym | `SparkFun-Hardware:Stand_off` | `—` | ? |
|     | 1 | sym | `SparkFun-RF:ESP_THING_PLUS_LOGICAL` | `—` | 28 |
|     | 1 | fp | `KML-Custom:buck_logo` | `—` | ? |
|     | 1 | sym | `BREAD_Slice-rescue:+5V-power` | `—` | 1 |
|     | 1 | sym | `BREAD_Slice-rescue:MAX31855KASA-Sensor_Temperature` | `—` | 7 |
|     | 1 | fp | `KML-Custom:MicroSD_5025700893` | `—` | 14 |
|     | 1 | sym | `BREAD_Slice-rescue:Term_2-OCI_UPL_10_Connectors` | `—` | 2 |
|     | 1 | sym | `Solar-Battery-Charger-rescue:PWR_FLAG-power` | `—` | 1 |
|     | 1 | sym | `Solar-Battery-Charger-rescue:SI7288DP-T1-GE3-SI7288DP-T1-GE3` | `—` | 8 |
|     | 1 | fp | `OCI_UPL_FOOTPRINTS:C_2312` | `—` | 2 |
|     | 1 | fp | `KMLib_Connectors:SAMTEC_PCIE-036-02-X-D-TH` | `—` | 38 |
|     | 1 | sym | `KMLib_Connectors:PCIE-036-02-X-D-TH` | `—` | 36 |
|     | 1 | sym | `kml-custom:SJ-3524-SMT` | `—` | 4 |
