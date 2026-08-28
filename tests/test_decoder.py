"""Decoder correctness regression tests."""

from custom_components.solarbridge.decoder import decode_value


def sensor(data_type="uint16", **overrides):
    value = {"address": 10, "data_type": data_type, "scale": 1, "offset": 0, "word_order": "low_high"}
    value.update(overrides)
    return value


def test_low_word_first_multiregister_value():
    assert decode_value(sensor("uint32"), {10: 0x5678, 11: 0x1234}) == 0x12345678


def test_non_contiguous_multiregister_value():
    definition = sensor("uint32", addresses=[10, 12])
    assert decode_value(definition, {10: 0x5678, 11: 0xFFFF, 12: 0x1234}) == 0x12345678


def test_all_multiregister_words_are_required():
    try:
        decode_value(sensor("uint32"), {10: 1})
    except KeyError as err:
        assert err.args == (11,)
    else:
        raise AssertionError("missing high word was silently ignored")


def test_signed_16_bit_value():
    assert decode_value(sensor("int16"), {10: 0xFF9C}) == -100


def test_bitmask_ignores_unrelated_flags():
    assert decode_value(sensor(bitmask=0b11), {10: 0b101101}) == 1
    assert decode_value(sensor(bitmask=0b10, bitshift=1), {10: 0b101101}) == 0


def test_decimal_hhmm():
    assert decode_value(sensor("decimal_hhmm"), {10: 1635}) == "16:35"
    assert decode_value(sensor("decimal_hhmm"), {10: 1679}) == "invalid"


def test_string_uses_every_register():
    assert (
        decode_value(
            sensor("string", register_count=3, word_order="high_low"),
            {10: 0x534F, 11: 0x4C41, 12: 0x5200},
        )
        == "SOLAR"
    )


def test_scale_offset_and_lookup():
    assert decode_value(sensor(scale=0.1, offset=-1000), {10: 1250}) == 25
    assert decode_value(sensor(lookup={"2": "Normal"}), {10: 2}) == "Normal"
