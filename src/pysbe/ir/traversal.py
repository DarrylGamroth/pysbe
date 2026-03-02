"""IR traversal helpers for generated token streams."""

from __future__ import annotations

from pysbe.ir.model import IrSchema, IrToken, Signal


def find_end_signal(
    tokens: list[IrToken],
    start_index: int,
    begin_signal: Signal,
    end_signal: Signal,
) -> int:
    """Find matching end signal index for a begin token."""

    depth = 0
    for index in range(start_index, len(tokens)):
        signal = tokens[index].signal
        if signal == begin_signal:
            depth += 1
        elif signal == end_signal:
            depth -= 1
            if depth == 0:
                return index
    raise ValueError(
        f"matching {end_signal.value} not found for {begin_signal.value} at index {start_index}"
    )


def collect_tokens(
    tokens: list[IrToken],
    begin_signal: Signal,
    end_signal: Signal,
) -> list[list[IrToken]]:
    """Collect token substreams enclosed by begin/end pairs."""

    segments: list[list[IrToken]] = []
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if token.signal == begin_signal:
            end_index = find_end_signal(tokens, index, begin_signal, end_signal)
            segments.append(tokens[index : end_index + 1])
            index = end_index + 1
            continue
        index += 1
    return segments


def collect_fields(tokens: list[IrToken]) -> list[list[IrToken]]:
    """Collect field token segments."""

    return collect_tokens(tokens, Signal.BEGIN_FIELD, Signal.END_FIELD)


def collect_groups(tokens: list[IrToken]) -> list[list[IrToken]]:
    """Collect repeating-group token segments."""

    return collect_tokens(tokens, Signal.BEGIN_GROUP, Signal.END_GROUP)


def collect_var_data(tokens: list[IrToken]) -> list[list[IrToken]]:
    """Collect var-data token segments."""

    return collect_tokens(tokens, Signal.BEGIN_VAR_DATA, Signal.END_VAR_DATA)


def get_message_body(schema_ir: IrSchema, message_id: int) -> list[IrToken]:
    """Return message tokens between BEGIN_MESSAGE and END_MESSAGE."""

    tokens = schema_ir.message(message_id)
    if tokens is None:
        raise KeyError(f"message id not found: {message_id}")
    if len(tokens) < 2:
        return []
    return tokens[1:-1]
