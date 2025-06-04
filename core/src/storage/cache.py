import gc
from trezorcrypto import random  # avoid pulling in trezor.crypto
from typing import TYPE_CHECKING

from trezor import utils
from trezor.crypto import se_thd89

if TYPE_CHECKING:
    from typing import Sequence, TypeVar, overload

    T = TypeVar("T")


_MAX_SESSIONS_COUNT = 10
_SESSIONLESS_FLAG = 128
_SESSION_ID_LENGTH = 32

# Traditional cache keys
APP_COMMON_SEED = 0
APP_COMMON_AUTHORIZATION_TYPE = 1
APP_COMMON_AUTHORIZATION_DATA = 2
APP_COMMON_NONCE = 3
if not utils.BITCOIN_ONLY:
    APP_COMMON_DERIVE_CARDANO = 4
    APP_CARDANO_ICARUS_SECRET = 5
    APP_CARDANO_ICARUS_TREZOR_SECRET = 6
    APP_MONERO_LIVE_REFRESH = 7

# Keys that are valid across sessions
APP_COMMON_SEED_WITHOUT_PASSPHRASE = 0 | _SESSIONLESS_FLAG
APP_COMMON_SAFETY_CHECKS_TEMPORARY = 1 | _SESSIONLESS_FLAG
STORAGE_DEVICE_EXPERIMENTAL_FEATURES = 2 | _SESSIONLESS_FLAG
APP_COMMON_REQUEST_PIN_LAST_UNLOCK = 3 | _SESSIONLESS_FLAG
APP_COMMON_BUSY_DEADLINE_MS = 4 | _SESSIONLESS_FLAG

SESSION_DIRIVE_CARDANO = False

_NONCE_CACHE = bytearray(32)


# === Homescreen storage ===
# This does not logically belong to the "cache" functionality, but the cache module is
# a convenient place to put this.
# When a Homescreen layout is instantiated, it checks the value of `homescreen_shown`
# to know whether it should render itself or whether the result of a previous instance
# is still on. This way we can avoid unnecessary fadeins/fadeouts when a workflow ends.
HOMESCREEN_ON = object()
LOCKSCREEN_ON = object()
BUSYSCREEN_ON = object()
homescreen_shown: object | None = None

_show_update_res_confirm = True


class InvalidSessionError(Exception):
    pass


class DataCache:
    fields: Sequence[int]

    def __init__(self) -> None:
        self.data = [bytearray(f + 1) for f in self.fields]

    def set(self, key: int, value: bytes) -> None:
        utils.ensure(key < len(self.fields))
        utils.ensure(len(value) <= self.fields[key])
        self.data[key][0] = 1
        self.data[key][1:] = value

    if TYPE_CHECKING:

        @overload
        def get(self, key: int) -> bytes | None:
            ...

        @overload
        def get(self, key: int, default: T) -> bytes | T:  # noqa: F811
            ...

    def get(self, key: int, default: T | None = None) -> bytes | T | None:  # noqa: F811
        utils.ensure(key < len(self.fields))
        if self.data[key][0] != 1:
            return default
        return bytes(self.data[key][1:])

    def is_set(self, key: int) -> bool:
        utils.ensure(key < len(self.fields))
        return self.data[key][0] == 1

    def delete(self, key: int) -> None:
        utils.ensure(key < len(self.fields))
        self.data[key][:] = b"\x00"

    def clear(self) -> None:
        for i in range(len(self.fields)):
            self.delete(i)


class SessionCache(DataCache):  # 会话缓存类，继承自DataCache
    def __init__(self) -> None:  # 初始化方法
        self.session_id = bytearray(_SESSION_ID_LENGTH)  # 创建会话ID字节数组
        if utils.BITCOIN_ONLY:  # 如果只支持比特币
            self.fields = (  # 定义字段大小元组
                64,  # APP_COMMON_SEED - 通用种子，64字节
                2,  # APP_COMMON_AUTHORIZATION_TYPE - 授权类型，2字节
                128,  # APP_COMMON_AUTHORIZATION_DATA - 授权数据，128字节
                32,  # APP_COMMON_NONCE - 随机数，32字节
            )
        else:  # 如果支持多种币种
            self.fields = (  # 定义字段大小元组
                64,  # APP_COMMON_SEED - 通用种子，64字节
                2,  # APP_COMMON_AUTHORIZATION_TYPE - 授权类型，2字节
                128,  # APP_COMMON_AUTHORIZATION_DATA - 授权数据，128字节
                32,  # APP_COMMON_NONCE - 随机数，32字节
                1,  # APP_COMMON_DERIVE_CARDANO - Cardano派生标志，1字节
                96,  # APP_CARDANO_ICARUS_SECRET - Cardano Icarus密钥，96字节
                96,  # APP_CARDANO_ICARUS_TREZOR_SECRET - Cardano Trezor密钥，96字节
                1,  # APP_MONERO_LIVE_REFRESH - Monero实时刷新标志，1字节
            )
        self.last_usage = 0  # 最后使用时间戳，初始化为0
        super().__init__()  # 调用父类初始化方法

    def export_session_id(self) -> bytes:  # 导出会话ID方法
        # generate a new session id if we don't have it yet
        if not self.session_id:  # 如果还没有会话ID
            self.session_id[:] = random.bytes(_SESSION_ID_LENGTH)  # 生成新的随机会话ID
        # export it as immutable bytes
        return bytes(self.session_id)  # 返回不可变的字节对象

    def clear(self) -> None:  # 清空缓存方法
        super().clear()  # 调用父类清空方法
        self.last_usage = 0  # 重置最后使用时间
        self.session_id[:] = b""  # 清空会话ID


class SessionlessCache(DataCache):  # 无会话缓存类，继承自DataCache
    def __init__(self) -> None:  # 初始化方法
        self.fields = (  # 定义字段大小元组
            64,  # APP_COMMON_SEED_WITHOUT_PASSPHRASE - 无密码种子，64字节
            1,  # APP_COMMON_SAFETY_CHECKS_TEMPORARY - 临时安全检查，1字节
            1,  # STORAGE_DEVICE_EXPERIMENTAL_FEATURES - 实验性功能，1字节
            8,  # APP_COMMON_REQUEST_PIN_LAST_UNLOCK - 最后PIN解锁请求，8字节
            8,  # APP_COMMON_BUSY_DEADLINE_MS - 忙碌截止时间(毫秒)，8字节
        )
        super().__init__()  # 调用父类初始化方法


# XXX
# Allocation notes:
# Instantiation of a DataCache subclass should make as little garbage as possible, so
# that the preallocated bytearrays are compact in memory.
# That is why the initialization is two-step: first create appropriately sized
# bytearrays, then later call `clear()` on all the existing objects, which resets them
# to zero length. This is producing some trash - `b[:]` allocates a slice.

_SESSIONS: list[SessionCache] = []  # 会话列表，存储所有会话缓存对象
for _ in range(_MAX_SESSIONS_COUNT):  # 循环创建最大会话数量的会话对象
    _SESSIONS.append(SessionCache())  # 添加新的会话缓存到列表

_SESSIONLESS_CACHE = SessionlessCache()  # 创建无会话缓存实例

for session in _SESSIONS:  # 遍历所有会话
    session.clear()  # 清空每个会话
_SESSIONLESS_CACHE.clear()  # 清空无会话缓存

_SESSION_ID = bytearray(_SESSION_ID_LENGTH)  # 创建全局会话ID字节数组

gc.collect()  # 执行垃圾回收


_active_session_idx: int | None = None  # 当前活跃会话索引，初始为None
_session_usage_counter = 0  # 会话使用计数器


def start_session(received_session_id: bytes | None = None) -> bytes | None:  # 启动会话函数
    print("start_session start_session start_session start_session")
    if not utils.USE_THD89:  # 如果不使用THD89安全元件
        global _active_session_idx  # 声明全局变量
        global _session_usage_counter  # 声明全局变量

        if (  # 如果接收到的会话ID不为空且长度不正确
            received_session_id is not None
            and len(received_session_id) != _SESSION_ID_LENGTH
        ):
            # Prevent the caller from setting received_session_id=b"" and finding a cleared
            # session. More generally, short-circuit the session id search, because we know
            # that wrong-length session ids should not be in cache.
            # Reduce to "session id not provided" case because that's what we do when
            # caller supplies an id that is not found.
            received_session_id = None  # 将接收到的会话ID设为None

        _session_usage_counter += 1  # 增加会话使用计数

        # attempt to find specified session id
        if received_session_id:  # 如果有指定的会话ID
            for i in range(_MAX_SESSIONS_COUNT):  # 遍历所有会话
                if _SESSIONS[i].session_id == received_session_id:  # 如果找到匹配的会话ID
                    _active_session_idx = i  # 设置活跃会话索引
                    _SESSIONS[i].last_usage = _session_usage_counter  # 更新最后使用时间
                    return received_session_id  # 返回会话ID

        # allocate least recently used session
        lru_counter = _session_usage_counter  # 最近最少使用计数器
        lru_session_idx = 0  # 最近最少使用会话索引
        for i in range(_MAX_SESSIONS_COUNT):  # 遍历所有会话
            if _SESSIONS[i].last_usage < lru_counter:  # 如果找到更少使用的会话
                lru_counter = _SESSIONS[i].last_usage  # 更新最少使用计数
                lru_session_idx = i  # 更新最少使用会话索引

        _active_session_idx = lru_session_idx  # 设置活跃会话为最少使用的会话
        selected_session = _SESSIONS[lru_session_idx]  # 获取选中的会话
        selected_session.clear()  # 清空选中的会话
        selected_session.last_usage = _session_usage_counter  # 设置最后使用时间
        return selected_session.export_session_id()  # 返回导出的会话ID
    else:  # 如果使用THD89安全元件
        received_session_id = se_thd89.start_session(received_session_id)  # 通过安全元件启动会话
        if received_session_id is not None:  # 如果收到有效的会话ID
            _SESSION_ID[:] = received_session_id  # 将会话ID复制到全局变量
        return received_session_id  # 返回会话ID


def end_current_session() -> None:  # 结束当前会话函数
    print("end_current_session end_current_session end_current_session end_current_session")
    if not utils.USE_THD89:  # 如果不使用THD89安全元件
        global _active_session_idx  # 声明全局变量

        if _active_session_idx is None:  # 如果没有活跃会话
            return  # 直接返回

        _SESSIONS[_active_session_idx].clear()  # 清空当前活跃会话
        _active_session_idx = None  # 重置活跃会话索引
    else:  # 如果使用THD89安全元件
        _SESSION_ID[:] = b""  # 清空全局会话ID
        se_thd89.end_session()  # 通过安全元件结束会话


def get_session_id() -> bytes:  # 获取会话ID函数
    print(f"_SESSION_ID: {_SESSION_ID}") 
    return bytes(_SESSION_ID)  # 返回全局会话ID的副本


def is_session_started() -> bool:  # 检查会话是否已启动函数
    if not utils.USE_THD89:  # 如果不使用THD89安全元件
        return _active_session_idx is not None  # 返回是否有活跃会话
    else:  # 如果使用THD89安全元件
        return se_thd89.session_is_open()  # 通过安全元件检查会话状态


def set(key: int, value: bytes) -> None:  # 设置缓存值函数
    if key & _SESSIONLESS_FLAG:  # 如果是无会话标志
        _SESSIONLESS_CACHE.set(key ^ _SESSIONLESS_FLAG, value)  # 在无会话缓存中设置值
        return  # 返回
    if not utils.USE_THD89:  # 如果不使用THD89安全元件
        if _active_session_idx is None:  # 如果没有活跃会话
            raise InvalidSessionError  # 抛出无效会话错误
        _SESSIONS[_active_session_idx].set(key, value)  # 在当前会话中设置值
    else:  # 如果使用THD89安全元件
        if key == APP_COMMON_NONCE:  # 如果是随机数键
            _NONCE_CACHE[:] = value  # 将值复制到随机数缓存
        return  # 返回


def set_int(key: int, value: int) -> None:  # 设置整数值函数
    if key & _SESSIONLESS_FLAG:  # 如果是无会话标志
        length = _SESSIONLESS_CACHE.fields[key ^ _SESSIONLESS_FLAG]  # 获取字段长度
    elif _active_session_idx is None:  # 如果没有活跃会话
        raise InvalidSessionError  # 抛出无效会话错误
    else:  # 否则
        length = _SESSIONS[_active_session_idx].fields[key]  # 获取当前会话的字段长度

    encoded = value.to_bytes(length, "big")  # 将整数编码为大端字节

    # Ensure that the value fits within the length. Micropython's int.to_bytes()
    # doesn't raise OverflowError.
    assert int.from_bytes(encoded, "big") == value  # 确保值在长度范围内

    set(key, encoded)  # 设置编码后的值


if TYPE_CHECKING:  # 如果在类型检查模式

    @overload  # 重载装饰器
    def get(key: int) -> bytes | None:  # 获取函数重载1
        ...

    @overload  # 重载装饰器
    def get(key: int, default: T) -> bytes | T:  # noqa: F811  # 获取函数重载2
        ...


def get(key: int, default: T | None = None) -> bytes | T | None:  # noqa: F811  # 获取缓存值函数
    if key & _SESSIONLESS_FLAG:  # 如果是无会话标志
        return _SESSIONLESS_CACHE.get(key ^ _SESSIONLESS_FLAG, default)  # 从无会话缓存获取值
    if not utils.USE_THD89:  # 如果不使用THD89安全元件
        if _active_session_idx is None:  # 如果没有活跃会话
            raise InvalidSessionError  # 抛出无效会话错误
        return _SESSIONS[_active_session_idx].get(key, default)  # 从当前会话获取值
    else:  # 如果使用THD89安全元件
        if key == APP_COMMON_NONCE:  # 如果是随机数键
            return bytes(_NONCE_CACHE)  # 返回随机数缓存的副本
        return None  # 返回None


def get_int(key: int, default: T | None = None) -> int | T | None:  # noqa: F811  # 获取整数值函数
    encoded = get(key)  # 获取编码的值
    if encoded is None:  # 如果值为None
        return default  # 返回默认值
    else:  # 否则
        return int.from_bytes(encoded, "big")  # 从大端字节解码为整数


def is_set(key: int) -> bool:  # 检查键是否已设置函数
    if key & _SESSIONLESS_FLAG:  # 如果是无会话标志
        return _SESSIONLESS_CACHE.is_set(key ^ _SESSIONLESS_FLAG)  # 检查无会话缓存中是否设置
    if _active_session_idx is None:  # 如果没有活跃会话
        raise InvalidSessionError  # 抛出无效会话错误
    return _SESSIONS[_active_session_idx].is_set(key)  # 检查当前会话中是否设置


def delete(key: int) -> None:  # 删除缓存值函数
    if key & _SESSIONLESS_FLAG:  # 如果是无会话标志
        return _SESSIONLESS_CACHE.delete(key ^ _SESSIONLESS_FLAG)  # 从无会话缓存删除
    if not utils.USE_THD89:  # 如果不使用THD89安全元件
        if _active_session_idx is None:  # 如果没有活跃会话
            raise InvalidSessionError  # 抛出无效会话错误
        return _SESSIONS[_active_session_idx].delete(key)  # 从当前会话删除
    else:  # 如果使用THD89安全元件
        if key == APP_COMMON_NONCE:  # 如果是随机数键
            _NONCE_CACHE[:] = b""  # 清空随机数缓存
    return None  # 返回None


if TYPE_CHECKING:  # 如果在类型检查模式
    from typing import Awaitable, Callable, TypeVar, ParamSpec  # 导入类型注解

    P = ParamSpec("P")  # 参数规范类型变量
    ByteFunc = Callable[P, bytes]  # 字节函数类型别名
    AsyncByteFunc = Callable[P, Awaitable[bytes]]  # 异步字节函数类型别名


def stored(key: int) -> Callable[[ByteFunc[P]], ByteFunc[P]]:
    def decorator(func: ByteFunc[P]) -> ByteFunc[P]:
        def wrapper(*args: P.args, **kwargs: P.kwargs):
            value = get(key)
            if value is None:
                value = func(*args, **kwargs)
                set(key, value)
            return value

        return wrapper

    return decorator


def stored_async(key: int) -> Callable[[AsyncByteFunc[P]], AsyncByteFunc[P]]:
    def decorator(func: AsyncByteFunc[P]) -> AsyncByteFunc[P]:
        async def wrapper(*args: P.args, **kwargs: P.kwargs):
            value = get(key)
            if value is None:
                value = await func(*args, **kwargs)
                set(key, value)
            return value

        return wrapper

    return decorator


def clear_all() -> None:
    global _active_session_idx

    _active_session_idx = None
    _SESSIONLESS_CACHE.clear()
    for session in _SESSIONS:
        session.clear()


def show_update_res_confirm(update_boot: bool = False) -> bool:
    if update_boot:
        return True
    global _show_update_res_confirm
    if _show_update_res_confirm:
        _show_update_res_confirm = False
        return True
    return False


def update_res_confirm_refresh():
    global _show_update_res_confirm
    if not _show_update_res_confirm:
        _show_update_res_confirm = True
