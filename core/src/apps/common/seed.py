from typing import TYPE_CHECKING

from storage import cache, device
from trezor import utils, wire
from trezor.crypto import bip32, hmac

from . import mnemonic
from .passphrase import get as get_passphrase

if TYPE_CHECKING:
    from .paths import Bip32Path, Slip21Path


class Slip21Node:
    """
    This class implements the SLIP-0021 hierarchical derivation of symmetric keys, see
    https://github.com/satoshilabs/slips/blob/master/slip-0021.md.
    """

    def __init__(self, seed: bytes | None = None, data: bytes | None = None) -> None:  # 初始化方法，接受种子或数据参数
        if utils.USE_THD89:  # 如果使用THD89安全元件
            if data is not None:  # 如果提供了数据
                self.data = data  # 直接使用提供的数据
            else:  # 否则
                from trezor.crypto import se_thd89  # 导入安全元件模块

                self.data = se_thd89.slip21_node()  # 从安全元件获取slip21节点数据
        else:  # 如果不使用安全元件
            assert seed is None or data is None, "Specify exactly one of: seed, data"  # 确保只指定seed或data中的一个
            if data is not None:  # 如果提供了数据
                self.data = data  # 直接使用提供的数据
            elif seed is not None:  # 如果提供了种子
                self.data = hmac(hmac.SHA512, b"Symmetric key seed", seed).digest()  # 使用HMAC-SHA512从种子生成数据
            else:  # 如果两者都没提供
                raise ValueError  # 抛出值错误异常

    def __del__(self) -> None:  # 析构方法
        del self.data  # 删除数据，清理内存

    def derive_path(self, path: Slip21Path) -> None:  # 派生路径方法
        for label in path:  # 遍历路径中的每个标签
            h = hmac(hmac.SHA512, self.data[0:32], b"\x00")  # 使用当前数据的前32字节作为密钥创建HMAC
            h.update(label)  # 更新HMAC，添加标签
            self.data = h.digest()  # 将HMAC摘要作为新的数据

    def key(self) -> bytes:  # 获取密钥方法
        return self.data[32:64]  # 返回数据的后32字节作为密钥

    def clone(self) -> "Slip21Node":  # 克隆当前节点方法
        return Slip21Node(data=self.data)  # 创建一个具有相同数据的新节点


if not utils.BITCOIN_ONLY:  # 如果不是仅比特币模式
    # === Cardano variant ===
    # We want to derive both the normal seed and the Cardano seed together, AND
    # expose a method for Cardano to do the same

    async def derive_and_store_roots(ctx: wire.Context) -> None:  # 派生并存储根密钥的异步函数
        if not device.is_initialized():  # 如果设备未初始化
            raise wire.NotInitialized("Device is not initialized")  # 抛出未初始化异常

        if not utils.USE_THD89:  # 如果不使用THD89安全元件
            need_seed = not cache.is_set(cache.APP_COMMON_SEED)  # 检查是否需要生成通用种子
            need_cardano_secret = cache.get(  # 检查是否需要生成Cardano密钥
                cache.APP_COMMON_DERIVE_CARDANO
            ) and not cache.is_set(cache.APP_CARDANO_ICARUS_SECRET)

            if not need_seed and not need_cardano_secret:  # 如果都不需要
                return  # 直接返回

            passphrase = await get_passphrase(ctx)  # 获取密码短语

            if need_seed:  # 如果需要生成通用种子
                common_seed = mnemonic.get_seed(passphrase, progress_bar=False)  # 使用助记词和密码短语生成种子
                cache.set(cache.APP_COMMON_SEED, common_seed)  # 将种子存入缓存

            if need_cardano_secret:  # 如果需要生成Cardano密钥
                from apps.cardano.seed import derive_and_store_secrets  # 导入Cardano密钥派生模块

                derive_and_store_secrets(passphrase)  # 派生并存储Cardano密钥
        else:  # 如果使用THD89安全元件
            from trezor.crypto import se_thd89  # 导入安全元件模块

            state = se_thd89.get_session_state()  # 获取会话状态

            if not state[0] & 0x80:  # 如果会话未激活
                passphrase = await get_passphrase(ctx)  # 获取密码短语
                mnemonic.get_seed(passphrase, progress_bar=False)  # 使用助记词和密码短语生成种子

                if cache.SESSION_DIRIVE_CARDANO:  # 如果需要派生Cardano密钥
                    from apps.cardano.seed import derive_and_store_secrets  # 导入Cardano密钥派生模块

                    derive_and_store_secrets(passphrase)  # 派生并存储Cardano密钥

    @cache.stored_async(cache.APP_COMMON_SEED)  # 使用缓存装饰器，缓存结果
    async def get_seed(ctx: wire.Context) -> bytes:  # 获取种子的异步函数
        await derive_and_store_roots(ctx)  # 派生并存储根密钥
        common_seed = cache.get(cache.APP_COMMON_SEED)  # 从缓存获取通用种子
        if not utils.USE_THD89:  # 如果不使用THD89安全元件
            assert common_seed is not None  # 断言种子不为空
            return common_seed  # 返回通用种子
        else:  # 如果使用THD89安全元件
            return b""  # 返回空字节，因为种子存储在安全元件中

else:  # 如果是仅比特币模式
    # === Bitcoin-only variant ===
    # We use the simple version of `get_seed` that never needs to derive anything else.

    @cache.stored_async(cache.APP_COMMON_SEED)  # 使用缓存装饰器，缓存结果
    async def get_seed(ctx: wire.Context) -> bytes:  # 获取种子的异步函数
        if not utils.USE_THD89:  # 如果不使用THD89安全元件
            passphrase = await get_passphrase(ctx)  # 获取密码短语
            return mnemonic.get_seed(passphrase, progress_bar=False)  # 返回使用助记词和密码短语生成的种子
        else:  # 如果使用THD89安全元件
            from trezor.crypto import se_thd89  # 导入安全元件模块

            state = se_thd89.get_session_state()  # 获取会话状态

            if not state[0] & 0x80:  # 如果会话未激活
                passphrase = await get_passphrase(ctx)  # 获取密码短语
                return mnemonic.get_seed(passphrase, progress_bar=False)  # 返回使用助记词和密码短语生成的种子
            else:  # 如果会话已激活
                return b""  # 返回空字节，因为种子存储在安全元件中


@cache.stored(cache.APP_COMMON_SEED_WITHOUT_PASSPHRASE)  # 使用缓存装饰器，缓存结果
def _get_seed_without_passphrase() -> bytes:  # 获取无密码短语种子的内部函数
    if not device.is_initialized():  # 如果设备未初始化
        raise Exception("Device is not initialized")  # 抛出异常
    return mnemonic.get_seed(progress_bar=False)  # 返回仅使用助记词生成的种子


def derive_node_without_passphrase(  # 无密码短语派生节点函数
    path: Bip32Path, curve_name: str = "secp256k1"  # 接受路径和曲线名称参数
) -> bip32.HDNode:  # 返回HD节点
    seed = _get_seed_without_passphrase()  # 获取无密码短语种子
    node = bip32.from_seed(seed, curve_name)  # 从种子创建HD节点
    node.derive_path(path)  # 派生路径
    return node  # 返回派生后的节点


def derive_fido_node_with_se(  # 使用安全元件派生FIDO节点函数
    path: Bip32Path, curve_name: str = "nist256p1"  # 接受路径和曲线名称参数
) -> bip32.HDNode:  # 返回HD节点
    from trezor.crypto import se_thd89  # 导入安全元件模块

    se_thd89.fido_seed()  # 获取FIDO种子
    node = bip32.HDNode(  # 创建HD节点
        depth=0,  # 深度为0
        fingerprint=0,  # 指纹为0
        child_num=0,  # 子编号为0
        chain_code=bytearray(32),  # 链码为32字节的空数组
        public_key=bytearray(33),  # 公钥为33字节的空数组
        curve_name=curve_name,  # 使用指定的曲线
    )
    node.derive_fido_path(path)  # 派生FIDO路径
    return node  # 返回派生后的节点


def derive_slip21_node_without_passphrase(path: Slip21Path) -> Slip21Node:  # 无密码短语派生SLIP21节点函数
    if utils.USE_THD89:  # 如果使用THD89安全元件
        from trezor.crypto import se_thd89  # 导入安全元件模块

        node = Slip21Node(data=se_thd89.slip21_fido_node())  # 使用安全元件的FIDO节点数据创建SLIP21节点
    else:  # 如果不使用安全元件
        seed = _get_seed_without_passphrase()  # 获取无密码短语种子
        node = Slip21Node(seed)  # 使用种子创建SLIP21节点
    node.derive_path(path)  # 派生路径

    return node  # 返回派生后的节点


def remove_ed25519_prefix(pubkey: bytes) -> bytes:  # 移除Ed25519前缀函数
    # 0x01 prefix is not part of the actual public key, hence removed
    return pubkey[1:]  # 返回去除第一个字节后的公钥
