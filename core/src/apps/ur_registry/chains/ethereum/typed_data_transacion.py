import re
from typing import Any, Optional
from ubinascii import unhexlify

from trezor import io, messages
from trezor.enums import EthereumDataType
from trezor.wire import QR_CONTEXT

from . import get_derivation_path
from .eth_sign_request import EthSignRequest

LOCAL_CTL = io.LOCAL_CTL()


class EthereumTypedDataTransacion:
    def __init__(self, req: EthSignRequest):
        self.req = req
        self.resp = None
        self.qr = None

    def get_data(self):
        return self.req.get_sign_data().decode()

    @staticmethod
    def sanitize_typed_data(data: dict) -> dict:
        """Remove properties from a message object that are not defined per EIP-712."""
        REQUIRED_KEYS = ("types", "primaryType", "domain", "message")
        sanitized_data = {key: data[key] for key in REQUIRED_KEYS}
        sanitized_data["types"].setdefault("EIP712Domain", [])
        return sanitized_data

    @staticmethod
    def is_array(type_name: str) -> bool:
        return type_name[-1] == "]"

    @staticmethod
    def parse_type_n(type_name: str) -> int:
        """Parse N from type<N>. Example: "uint256" -> 256."""
        match = re.search(r"\d+$", type_name)
        if match:
            return int(match.group(0))
        else:
            raise ValueError(f"Could not parse type<N> from {type_name}.")

    @staticmethod
    def typeof_array(type_name: str) -> str:
        return type_name[: type_name.rindex("[")]

    @staticmethod
    def get_byte_size_for_int_type(int_type: str) -> int:
        return EthereumTypedDataTransacion.parse_type_n(int_type) // 8

    @staticmethod
    def parse_array_n(type_name: str) -> Optional[int]:
        """Parse N in type[<N>] where "type" can itself be an array type."""
        # sign that it is a dynamic array - we do not know <N>
        if type_name.endswith("[]"):
            return None

        start_idx = type_name.rindex("[") + 1
        return int(type_name[start_idx:-1])

    @staticmethod
    def get_field_type(type_name: str, types: dict) -> messages.EthereumFieldType:
        data_type = None
        size = None
        entry_type = None
        struct_name = None

        if EthereumTypedDataTransacion.is_array(type_name):
            data_type = EthereumDataType.ARRAY
            size = EthereumTypedDataTransacion.parse_array_n(type_name)
            member_typename = EthereumTypedDataTransacion.typeof_array(type_name)
            entry_type = EthereumTypedDataTransacion.get_field_type(
                member_typename, types
            )
            # Not supporting nested arrays currently
            if entry_type.data_type == EthereumDataType.ARRAY:
                raise NotImplementedError("Nested arrays are not supported")
        elif type_name.startswith("uint"):
            data_type = EthereumDataType.UINT
            size = EthereumTypedDataTransacion.get_byte_size_for_int_type(type_name)
        elif type_name.startswith("int"):
            data_type = EthereumDataType.INT
            size = EthereumTypedDataTransacion.get_byte_size_for_int_type(type_name)
        elif type_name.startswith("bytes"):
            data_type = EthereumDataType.BYTES
            size = (
                None
                if type_name == "bytes"
                else EthereumTypedDataTransacion.parse_type_n(type_name)
            )
        elif type_name == "string":
            data_type = EthereumDataType.STRING
        elif type_name == "bool":
            data_type = EthereumDataType.BOOL
        elif type_name == "address":
            data_type = EthereumDataType.ADDRESS
        elif type_name in types:
            data_type = EthereumDataType.STRUCT
            size = len(types[type_name])
            struct_name = type_name
        else:
            raise ValueError(f"Unsupported type name: {type_name}")

        return messages.EthereumFieldType(
            data_type=data_type,
            size=size,
            entry_type=entry_type,
            struct_name=struct_name,
        )

    @staticmethod
    def decode_hex(value: str) -> bytes:
        if value.startswith("0x") or value.startswith("0X"):
            return unhexlify(value[2:])
        else:
            return unhexlify(value)

    @staticmethod
    def encode_data(value: Any, type_name: str) -> bytes:
        if type_name.startswith("bytes"):
            return EthereumTypedDataTransacion.decode_hex(value)
        elif type_name == "string":
            return value.encode()
        # elif type_name.startswith(("int", "uint")):
        elif type_name.startswith("int") or type_name.startswith("uint"):
            byte_length = EthereumTypedDataTransacion.get_byte_size_for_int_type(
                type_name
            )
            return int(value).to_bytes(byte_length, "big")
        elif type_name == "bool":
            if not isinstance(value, bool):
                raise ValueError(f"Invalid bool value - {value}")
            return int(value).to_bytes(1, "big")
        elif type_name == "address":
            return EthereumTypedDataTransacion.decode_hex(value)

        # We should be receiving only atomic, non-array types
        raise ValueError(
            f"Unsupported data type for direct field encoding: {type_name}"
        )

    async def initial_tx(self):
        import ujson as json

        msg = json.loads(self.get_data())
        data = EthereumTypedDataTransacion.sanitize_typed_data(msg)

        request = messages.EthereumSignTypedData(
            address_n=get_derivation_path(),
            primary_type=data["primaryType"],
            metamask_v4_compat=True,
            definitions=None,
        )

        from apps.ethereum.sign_typed_data import sign_typed_data
        from trezor import loop
        from apps.ur_registry.chains.ethereum.eth_signature import EthSignature
        from apps.ur_registry.ur_py.ur.ur_encoder import UREncoder

        # pyright: off
        task = sign_typed_data(QR_CONTEXT, request)
        self.resp = await loop.spawn(task)
        # pyright: on
        self.signature = self.resp.signature
        eth_signature = EthSignature(
            request_id=self.req.get_request_id(),
            signature=self.signature,
            origin="OneKey".encode(),
        )
        ur = eth_signature.ur_encode()
        encoded = UREncoder.encode(ur).upper()
        self.qr = encoded

    async def run(self):
        import ujson as json

        msg = json.loads(self.get_data())
        data = EthereumTypedDataTransacion.sanitize_typed_data(msg)
        types = msg["types"]

        response = await QR_CONTEXT.qr_ctx_resp()
        if response is None:
            return

        if messages.EthereumTypedDataStructRequest.is_type_of(response):
            struct_name = response.name
            members: list["messages.EthereumStructMember"] = []
            for field in types[struct_name]:
                field_type = EthereumTypedDataTransacion.get_field_type(
                    field["type"], types
                )
                struct_member = messages.EthereumStructMember(
                    type=field_type,
                    name=field["name"],
                )
                members.append(struct_member)

            request = messages.EthereumTypedDataStructAck(members=members)
            await QR_CONTEXT.qr_ctx_req(request)
            LOCAL_CTL.ctrl(True)
        elif messages.EthereumTypedDataValueRequest.is_type_of(response):
            root_index = response.member_path[0]
            # Index 0 is for the domain data, 1 is for the actual message
            if root_index == 0:
                member_typename = "EIP712Domain"
                member_data = data["domain"]
            elif root_index == 1:
                member_typename = data["primaryType"]
                member_data = data["message"]
            else:
                raise ValueError("Root index can only be 0 or 1")

            for index in response.member_path[1:]:
                if isinstance(member_data, dict):
                    member_def = types[member_typename][index]
                    member_typename = member_def["type"]
                    member_data = member_data[member_def["name"]]
                elif isinstance(member_data, list):
                    member_typename = EthereumTypedDataTransacion.typeof_array(
                        member_typename
                    )
                    member_data = member_data[index]

            if isinstance(member_data, list):
                # Sending the length as uint16
                encoded_data = len(member_data).to_bytes(2, "big")
            else:
                encoded_data = EthereumTypedDataTransacion.encode_data(
                    member_data, member_typename
                )

            request = messages.EthereumTypedDataValueAck(value=encoded_data)
            await QR_CONTEXT.qr_ctx_req(request)
            LOCAL_CTL.ctrl(True)
        elif messages.ButtonRequest.is_type_of(response):
            request = messages.ButtonAck()
            await QR_CONTEXT.qr_ctx_req(request)
            LOCAL_CTL.ctrl(True)
        else:
            raise ValueError(f"Error messages {response}.")