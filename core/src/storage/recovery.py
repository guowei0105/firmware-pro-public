from micropython import const

from storage import common
from trezor import utils

# Namespace:
_NAMESPACE = common.APP_RECOVERY

# fmt: off
if utils.USE_THD89:
    from storage.device import (
        _IN_PROGRESS,
        _DRY_RUN,
        _SLIP39_IDENTIFIER_RECOVER,
        _SLIP39_THRESHOLD,
        _REMAINING,
        _SLIP39_ITERATION_E_RECOVER,
        _SLIP39_GROUP_COUNT,
    )
else:
    # Keys:
    _IN_PROGRESS                = (0x00)  # bool
    _DRY_RUN                    = (0x01)  # bool
    _SLIP39_IDENTIFIER_RECOVER  = (0x03)  # bytes
    _SLIP39_THRESHOLD           = (0x04)  # int
    _REMAINING                  = (0x05)  # int
    _SLIP39_ITERATION_E_RECOVER = (0x06)  # int
    _SLIP39_GROUP_COUNT         = (0x07)  # int

# Deprecated Keys:
# _WORD_COUNT                = const(0x02)  # int
# fmt: on

# Default values:
_DEFAULT_SLIP39_GROUP_COUNT = const(1)


def _require_progress() -> None:
    if not is_in_progress():
        raise RuntimeError


def set_in_progress(val: bool) -> None:
    common.set_bool(_NAMESPACE, _IN_PROGRESS, val)


def is_in_progress() -> bool:
    return common.get_bool(_NAMESPACE, _IN_PROGRESS)


def set_dry_run(val: bool) -> None:
    _require_progress()
    common.set_bool(_NAMESPACE, _DRY_RUN, val)


def is_dry_run() -> bool:
    _require_progress()
    return common.get_bool(_NAMESPACE, _DRY_RUN)


def set_slip39_identifier(identifier: int) -> None:
    _require_progress()
    common.set_uint16(_NAMESPACE, _SLIP39_IDENTIFIER_RECOVER, identifier)


def get_slip39_identifier() -> int | None:
    _require_progress()
    return common.get_uint16(_NAMESPACE, _SLIP39_IDENTIFIER_RECOVER)


def set_slip39_iteration_exponent(exponent: int) -> None:
    _require_progress()
    common.set_uint8(_NAMESPACE, _SLIP39_ITERATION_E_RECOVER, exponent)


def get_slip39_iteration_exponent() -> int | None:
    _require_progress()
    return common.get_uint8(_NAMESPACE, _SLIP39_ITERATION_E_RECOVER)


def set_slip39_group_count(group_count: int) -> None:
    _require_progress()
    common.set_uint8(_NAMESPACE, _SLIP39_GROUP_COUNT, group_count)


def get_slip39_group_count() -> int:
    _require_progress()
    return (
        common.get_uint8(_NAMESPACE, _SLIP39_GROUP_COUNT) or _DEFAULT_SLIP39_GROUP_COUNT
    )


def set_slip39_remaining_shares(shares_remaining: int, group_index: int) -> None:
    """
    We store the remaining shares as a bytearray of length group_count.
    Each byte represents share remaining for group of that group_index.
    0x10 (16) was chosen as the default value because it's the max
    share count for a group.
    """
    from trezor.crypto.slip39 import MAX_SHARE_COUNT

    _require_progress()
    remaining = common.get(_NAMESPACE, _REMAINING)
    group_count = get_slip39_group_count()
    if not group_count:
        raise RuntimeError
    if remaining is None:
        remaining = bytearray([MAX_SHARE_COUNT] * group_count)
    remaining = bytearray(remaining)
    remaining[group_index] = shares_remaining
    common.set(_NAMESPACE, _REMAINING, remaining)


def get_slip39_remaining_shares(group_index: int) -> int | None:
    from trezor.crypto.slip39 import MAX_SHARE_COUNT

    _require_progress()
    remaining = common.get(_NAMESPACE, _REMAINING)
    if remaining is None or remaining[group_index] == MAX_SHARE_COUNT:
        return None
    else:
        return remaining[group_index]


def fetch_slip39_remaining_shares() -> list[int] | None:
    _require_progress()
    remaining = common.get(_NAMESPACE, _REMAINING)
    if not remaining:
        return None

    group_count = get_slip39_group_count()
    if not group_count:
        raise RuntimeError
    return list(remaining[:group_count])


SECRET_CHECKED: bytes | None = None
EXTEND_SHARE_FLAG: bool = False


def set_extend_share() -> None:
    global EXTEND_SHARE_FLAG
    EXTEND_SHARE_FLAG = True


def is_extend_share() -> bool:
    return EXTEND_SHARE_FLAG


def get_slip39_checked_secret() -> bytes:
    if SECRET_CHECKED is None:
        raise RuntimeError
    return SECRET_CHECKED


def set_slip39_checked_secret(secret: bytes) -> None:
    global SECRET_CHECKED
    SECRET_CHECKED = secret


def clear_slip39_extend_share_state() -> None:
    global SECRET_CHECKED, EXTEND_SHARE_FLAG
    SECRET_CHECKED = None
    EXTEND_SHARE_FLAG = False


def end_progress() -> None:
    from . import recovery_shares

    _require_progress()
    common.delete(_NAMESPACE, _IN_PROGRESS)
    common.delete(_NAMESPACE, _DRY_RUN)
    common.delete(_NAMESPACE, _SLIP39_IDENTIFIER_RECOVER)
    common.delete(_NAMESPACE, _SLIP39_THRESHOLD)
    common.delete(_NAMESPACE, _REMAINING)
    common.delete(_NAMESPACE, _SLIP39_ITERATION_E_RECOVER)
    common.delete(_NAMESPACE, _SLIP39_GROUP_COUNT)
    recovery_shares.delete()
