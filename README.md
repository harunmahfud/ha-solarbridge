# SolarBridge

Local-only Modbus TCP monitoring for hybrid solar inverters in Home Assistant. No vendor cloud, account, API key, or YAML configuration is required.

> [!WARNING]
> **Only Deye SUN-6K-SG05LP1-EU-SM2-P has been validated.** Every other model or profile is community-contributed and unverified. Register maps differ even between similarly named inverters; verify values before relying on them. See [supported hardware](SUPPORTED_HARDWARE.md).

SolarBridge is read-only. Write support is deliberately excluded from v1: incorrect register writes can alter safety-critical settings or damage equipment.

## Features

- UI config and options flows accepting IP addresses and hostnames
- Home Assistant-managed persistent Modbus connections shared safely across integrations and unit IDs
- Lazy connection and reconnection, serialized asynchronous access, and exponential reconnect backoff that preserves last-known-good data without counting deferred polls as failed connection attempts
- Profile-declared fast and slow polling tiers (minimum fast interval: 1 second)
- Correct Home Assistant device/state classes, diagnostics, and stable `{entry_id}_{register_key}` unique IDs
- Versioned, schema-validated register profiles and automatic unavailability after three consecutive read or decode failures
- Multiple independent inverter config entries

## HACS installation

SolarBridge requires Home Assistant 2026.9.0 or newer.

1. Open **HACS → Integrations**.
2. Select **⋮ → Custom repositories**.
3. Add `https://github.com/harunmahfud/ha-solarbridge` with category **Integration**.
4. Install **SolarBridge**, restart Home Assistant, then use **Settings → Devices & services → Add integration → SolarBridge**.

Port `502` is the default for RS485-to-TCP gateways. Deye WiFi/LAN loggers commonly expose their proprietary connection on port `8899`; only use that port when the logger also provides raw Modbus TCP.

## Profile contract

Profiles live under `custom_components/solarbridge/profiles/v1/`. Each YAML file declares FC03/FC04 ranges and polling tiers plus every entity's address, type, scale, offset, word order, optional bitmask, unit, device/state class, tier, and display name. Filenames are persistent config-entry identifiers and are never renamed without migration support.

The SM2-P profile reads only `3–112`, `150–279`, and `312–319`, all within the FC03 125-register limit. It intentionally excludes split-phase/L2 entities and exposes register `0x00A6` as signed **AUX Port Power** and `0x00C3` as diagnostic **AUX Status Raw**.

The profile also reads the Li-BMS telemetry block at registers `312–319`. Register 183 is the inverter's battery-terminal voltage, while register 317 is the voltage reported by the BMS; small differences between them are expected. The BMS block was validated by direct FC03 reads from the supported SUN-6K-SG05LP1-EU-SM2-P.

Register `0x009A` (154) is exposed read-only as **Inverter Output Voltage** (`uint16`, 0.1 V), following maintained Deye/Sunsynk single-phase register maps. The existing `150–249` read already includes this register, so the entity adds no Modbus request. Physical comparison with the SUN-6K-SG05LP1-EU-SM2-P inverter display was not possible in automated validation; treat the value as model-specific and verify it before relying on it for diagnostics.

### Power sign semantics

SolarBridge exposes the profile's decoded and scaled register values without
normalizing or inverting their signs. For the validated
SUN-6K-SG05LP1-EU-SM2-P profile, use these semantics:

| Register / entity | Positive | Negative | Notes |
| --- | --- | --- | --- |
| 169 · Grid power | Importing from grid | Exporting to grid | Signed `int16`, W |
| 173 · Inverter power | Supplying AC output | Absorbing AC power | Signed `int16`, W; this is the L1/output register and does not identify whether the source is PV, battery, or grid |
| 178 · Load power | Load consumption | Not expected from the unsigned register | `uint16`, W |
| 186/187 · PV1/PV2 power | PV generation | Not expected from the unsigned registers | Separate string values; no aggregate PV value is calculated |
| 190 · Battery power | Discharging | Charging | Signed `int16`, W |
| 191 · Battery current | Discharging | Charging | Signed `int16`, scaled to A; follows the battery-power direction |

Maintained Deye mappings identify register 175 as aggregate inverter output
power, while this exact profile currently exposes register 173 as L1/output
power. The values matched on the validated single-phase unit during read-only
sampling, but that does not establish equivalence on every firmware or model.
Register 175 is therefore not silently substituted or exposed without further
model validation.

## Development

```bash
python -m venv .venv
.venv/bin/pip install -r requirements-test.txt
.venv/bin/pytest
.venv/bin/ruff check custom_components tests
```

Raw register payloads are available only at debug log level under `custom_components.solarbridge` / `tmodbus`. Download redacted diagnostics from the integration's device page when reporting a problem.

## Lineage

SolarBridge is a clean-room rewrite inspired by [comdif/ha-solarmodbus](https://github.com/comdif/ha-solarmodbus) and the corrected [harunmahfud/ha-solarmodbus](https://github.com/harunmahfud/ha-solarmodbus) fork. Register mapping references came from [StephanJoubert/solarman](https://github.com/StephanJoubert/solarman). Card design inspiration came from [heavenknows1978/hass-deyecloud](https://github.com/heavenknows1978/hass-deyecloud) and [harunmahfud/hass-deyecloud](https://github.com/harunmahfud/hass-deyecloud). Details and licenses are in [ATTRIBUTION.md](ATTRIBUTION.md).
