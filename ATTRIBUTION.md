# Attribution and reference material

SolarBridge is a clean-room implementation. No source or YAML file was copied from the projects below. Their publicly documented behavior and register definitions were consulted as reference material:

- [comdif/ha-solarmodbus](https://github.com/comdif/ha-solarmodbus) — MIT; architectural inspiration.
- [harunmahfud/ha-solarmodbus](https://github.com/harunmahfud/ha-solarmodbus) — MIT; SG05LP1 SM2-P correction reference.
- [StephanJoubert/solarman](https://github.com/StephanJoubert/solarman) — MIT; public inverter register definitions.
- [Deye Modbus protocol V118](https://github.com/user-attachments/files/16597960/Deye.Modbus.protocol.V118.pdf), pages 21–24, and [davidrapan/ha-solarman](https://github.com/davidrapan/ha-solarman/blob/main/custom_components/solarman/inverter_definitions/deye_hybrid.yaml) — battery chemistry/control-basis settings, protection thresholds, and voltage TOU register reference.
- [heavenknows1978/hass-deyecloud](https://github.com/heavenknows1978/hass-deyecloud) and [harunmahfud/hass-deyecloud](https://github.com/harunmahfud/hass-deyecloud) — Apache-2.0; dashboard inspiration only.

SolarBridge's own code and newly authored profile are licensed under the repository's MIT License.
