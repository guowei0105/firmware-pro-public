from typing import TYPE_CHECKING

from trezor import ui
from trezor.enums import ButtonRequestType, TronResourceCode
from trezor.lvglui.i18n import gettext as _, keys as i18n_keys
from trezor.strings import format_amount
from trezor.ui.layouts import confirm_address, should_show_details_new
from trezor.ui.layouts.lvgl.altcoin import confirm_total_tron

from . import tokens

if TYPE_CHECKING:
    from typing import Awaitable
    from trezor.wire import Context


def require_confirm_data(ctx: Context, data: bytes, data_total: int) -> Awaitable[None]:
    from trezor.ui.layouts import confirm_data

    return confirm_data(
        ctx,
        "confirm_data",
        title=_(i18n_keys.TITLE__VIEW_DATA),
        description=_(i18n_keys.SUBTITLE__STR_BYTES).format(data_total),
        data=data,
        br_code=ButtonRequestType.SignTx,
    )


def require_confirm_tx(
    ctx: Context,
    from_address: str,
    to: str,
    value: int,
    token: tokens.TokenInfo | None = None,
) -> Awaitable[None]:
    from trezor.ui.layouts.lvgl.altcoin import confirm_total_tron_new

    return confirm_total_tron_new(
        ctx,
        title=format_amount_trx(value, token),
        from_address=from_address,
        to_address=to,
        banner_key=_(i18n_keys.BANNER_ENERGY_RENTAL)
        if check_provider(ctx, to)
        else None,
        banner_level=4,
    )


def check_provider(ctx: Context, to: str) -> bool:
    from apps.tron.providers import provider_by_address

    provider = provider_by_address(to)
    return bool(provider)


async def require_confirm_unknown_token(ctx: Context, contract_address: str) -> None:
    await confirm_address(
        ctx,
        _(i18n_keys.TITLE__UNKNOWN_TOKEN),
        contract_address,
        description=_(i18n_keys.LIST_KEY__CONTRACT__COLON),
        br_type="unknown_token",
        icon="A:/res/warning.png",
        icon_color=ui.ORANGE,
        br_code=ButtonRequestType.SignTx,
    )


async def require_confirm_show_more(
    ctx: Context,
    amount: str,
    toAddress: str,
) -> bool:
    from trezor.strings import strip_amount

    return await should_show_details_new(
        ctx,
        title=_(i18n_keys.TITLE__SEND_MULTILINE).format(strip_amount(amount)[0]),
        to_address=toAddress,
        banner_key=_(i18n_keys.BANNER_ENERGY_RENTAL)
        if toAddress and check_provider(ctx, toAddress)
        else None,
        banner_level=4 if toAddress and check_provider(ctx, toAddress) else 0,
    )


def require_confirm_fee(
    ctx: Context,
    token: tokens.TokenInfo | None = None,
    from_address: str | None = None,
    to_address: str | None = None,
    value: int = 0,
    fee_limit: int = 0,
) -> Awaitable[None]:
    from trezor.strings import strip_amount

    amount = format_amount_trx(value, token)
    striped_amount, striped = strip_amount(amount)
    fee_max = format_amount_trx(fee_limit, None)
    if token is None:
        total_amount = format_amount_trx(value + fee_limit, None)
    else:
        total_amount = None

    return confirm_total_tron(
        ctx,
        _(i18n_keys.TITLE__SEND_MULTILINE).format(striped_amount),
        from_address,
        to_address,
        amount,
        fee_max,
        total_amount,
        striped=striped,
    )


def require_confirm_freeze(
    ctx: Context,
    signer: str,
    frozen_balance: int | None = None,
    frozen_duration: int | None = None,
    resource: int | None = None,
    receiver_address: str | None = None,
) -> Awaitable[None]:
    from trezor.ui.layouts.lvgl import confirm_tron_freeze

    if resource is TronResourceCode.BANDWIDTH:
        res = _(i18n_keys.LIST_KEY__BANDWIDTH)
    elif resource == TronResourceCode.ENERGY:
        res = _(i18n_keys.LIST_KEY__ENERGY)
    else:
        res = None

    return confirm_tron_freeze(
        ctx,
        "Freeze" if receiver_address is not None else "Freeze Balance V2 Contract",
        signer,
        res,
        format_amount_trx(frozen_balance, None) if frozen_balance is not None else None,
        str(frozen_duration) if frozen_duration is not None else None,
        receiver_address,
    )


def require_confirm_unfreeze(
    ctx: Context,
    signer: str,
    resource: int | None = None,
    receiver_address: str | None = None,
    unfrozen_balance: int | None = None,
) -> Awaitable[None]:
    from trezor.ui.layouts.lvgl import confirm_tron_freeze

    if resource is TronResourceCode.BANDWIDTH:
        res = _(i18n_keys.LIST_KEY__BANDWIDTH)
    elif resource == TronResourceCode.ENERGY:
        res = _(i18n_keys.LIST_KEY__ENERGY)
    else:
        res = None
    return confirm_tron_freeze(
        ctx,
        "UnFreeze",
        signer,
        res,
        format_amount_trx(unfrozen_balance, None)
        if unfrozen_balance is not None
        else None,
        None,
        receiver_address,
    )


def require_confirm_unfreeze_v2(
    ctx: Context,
    signer: str,
    resource: int | None = None,
    unfrozen_balance: int | None = None,
) -> Awaitable[None]:
    from trezor.ui.layouts.lvgl import confirm_tron_unfreeze

    if resource is TronResourceCode.BANDWIDTH:
        res = _(i18n_keys.LIST_KEY__BANDWIDTH)
    elif resource == TronResourceCode.ENERGY:
        res = _(i18n_keys.LIST_KEY__ENERGY)
    else:
        res = None
    return confirm_tron_unfreeze(
        ctx,
        "UnFreeze Balance V2 Contract",
        signer,
        res,
        format_amount_trx(unfrozen_balance, None)
        if unfrozen_balance is not None
        else None,
    )


def require_confirm_delegate(
    ctx: Context,
    signer: str,
    resource: int | None = None,
    balance: int | None = None,
    receiver_address: str | None = None,
    lock: bool | None = None,
) -> Awaitable[None]:
    from trezor.ui.layouts.lvgl import confirm_tron_delegate

    if resource is TronResourceCode.BANDWIDTH:
        res = _(i18n_keys.LIST_KEY__BANDWIDTH)
    elif resource == TronResourceCode.ENERGY:
        res = _(i18n_keys.LIST_KEY__ENERGY)
    else:
        res = None
    return confirm_tron_delegate(
        ctx,
        "Delegate Resource Contract",
        signer,
        res,
        format_amount_trx(balance, None) if balance is not None else None,
        receiver_address,
        str(lock) if lock is not None else None,
    )


def require_confirm_undelegate(
    ctx: Context,
    signer: str,
    resource: int | None = None,
    balance: int | None = None,
    receiver_address: str | None = None,
    lock: bool | None = None,
) -> Awaitable[None]:
    from trezor.ui.layouts.lvgl import confirm_tron_delegate

    if resource is TronResourceCode.BANDWIDTH:
        res = _(i18n_keys.LIST_KEY__BANDWIDTH)
    elif resource == TronResourceCode.ENERGY:
        res = _(i18n_keys.LIST_KEY__ENERGY)
    else:
        res = None
    return confirm_tron_delegate(
        ctx,
        "UnDelegate Resource Contract",
        signer,
        res,
        format_amount_trx(balance, None) if balance is not None else None,
        receiver_address,
        str(lock) if lock is not None else None,
    )


def require_confirm_cancel_all_unfreeze_v2(
    ctx: Context,
    signer: str,
) -> Awaitable[None]:
    from trezor.ui.layouts.lvgl import confirm_tron_unfreeze

    return confirm_tron_unfreeze(ctx, "Cancel All UnStaking", signer, None, None)


def require_confirm_vote_witness(
    ctx: Context,
    signer: str,
    votes: list[tuple[str, int]],
    support: bool | None,
) -> Awaitable[None]:
    from trezor.ui.layouts.lvgl import confirm_tron_vote

    return confirm_tron_vote(
        ctx,
        "Vote for Witness"
        if (support is None or support)
        else "Remove Vote for Witness",
        signer,
        votes,
    )


def format_amount_trx(value: int, token: tokens.TokenInfo | None) -> str:
    if token:
        suffix = token.symbol
        decimals = token.decimals
    else:
        suffix = "TRX"
        decimals = 6

    return f"{format_amount(value, decimals)} {suffix}"
