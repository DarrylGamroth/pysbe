from __future__ import annotations

import numpy as np

from pysbe.runtime import (
    GroupFlyweight,
    MessageFlyweight,
    PositionPointer,
    read_primitive,
    read_vardata,
    shares_memory,
    to_numpy_uint8,
    view_primitive_array,
    write_primitive,
    write_vardata,
)


def test_to_numpy_uint8_is_zero_copy_for_bytearray() -> None:
    backing = bytearray(b"\x00\x01\x02\x03")
    array = to_numpy_uint8(backing, writable=True)
    assert array.dtype == np.uint8
    assert shares_memory(array, backing)

    array[1] = 44
    assert backing[1] == 44


def test_primitive_read_write_le_and_be() -> None:
    buffer = bytearray(32)

    write_primitive(buffer, 0, "uint16", 0x1122, byte_order="littleEndian")
    write_primitive(buffer, 2, "uint16", 0x1122, byte_order="bigEndian")
    write_primitive(buffer, 4, "int32", -77, byte_order="littleEndian")
    write_primitive(buffer, 8, "double", 3.25, byte_order="bigEndian")

    assert read_primitive(buffer, 0, "uint16", byte_order="littleEndian") == 0x1122
    assert read_primitive(buffer, 2, "uint16", byte_order="bigEndian") == 0x1122
    assert read_primitive(buffer, 4, "int32", byte_order="littleEndian") == -77
    assert read_primitive(buffer, 8, "double", byte_order="bigEndian") == 3.25


def test_primitive_array_views_are_zero_copy() -> None:
    buffer = bytearray(16)
    for idx, value in enumerate([11, 22, 33, 44]):
        write_primitive(buffer, idx * 4, "uint32", value, byte_order="littleEndian")

    array = view_primitive_array(buffer, 0, "uint32", 4, byte_order="littleEndian", writable=True)
    assert list(array) == [11, 22, 33, 44]
    assert shares_memory(array, buffer)

    array[2] = 99
    assert read_primitive(buffer, 8, "uint32", byte_order="littleEndian") == 99


def test_message_position_and_group_cursor() -> None:
    message = MessageFlyweight.wrap(
        bytearray(64),
        offset=8,
        acting_block_length=12,
        acting_version=2,
    )
    assert message.position == 20
    message.position = 30
    assert message.position == 30
    assert message.rewind() == 20

    pointer = PositionPointer(16)
    group = GroupFlyweight.wrap(bytearray(64), offset=0).wrap_group(
        bytearray(64),
        offset=16,
        count=2,
        block_length=4,
        position_ptr=pointer,
    )
    first = group.next()
    assert first.offset == 16
    assert pointer.get() == 20
    second = group.next()
    assert second.offset == 20
    assert pointer.get() == 24


def test_vardata_write_read_roundtrip() -> None:
    buffer = bytearray(64)
    next_position = write_vardata(buffer, 0, b"hello", length_type="uint8")
    assert next_position == 6
    data, end_position = read_vardata(buffer, 0, length_type="uint8")
    assert bytes(data) == b"hello"
    assert end_position == 6
