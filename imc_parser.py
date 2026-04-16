"""
IMC message definition parser.

Reads IMC.xml and builds a dictionary of message definitions
that can be used to deserialize binary IMC payloads from LSF files.
"""

import xml.etree.ElementTree as ET
from dataclasses import dataclass, field as dc_field
from typing import Optional


FIXED_TYPE_SIZES = {
    "int8_t": 1,
    "uint8_t": 1,
    "int16_t": 2,
    "uint16_t": 2,
    "int32_t": 4,
    "uint32_t": 4,
    "int64_t": 8,
    "fp32_t": 4,
    "fp64_t": 8,
}

VARIABLE_TYPES = {"plaintext", "rawdata", "message", "message-list"}


@dataclass
class FieldDef:
    name: str
    abbrev: str
    type: str
    unit: Optional[str] = None
    enum_values: dict = dc_field(default_factory=dict)
    bitfield_values: dict = dc_field(default_factory=dict)
    message_type: Optional[str] = None  # for typed inline messages
    prefix: Optional[str] = None

    @property
    def is_fixed(self) -> bool:
        return self.type in FIXED_TYPE_SIZES

    @property
    def fixed_size(self) -> int:
        return FIXED_TYPE_SIZES.get(self.type, 0)


@dataclass
class MessageDef:
    id: int
    name: str
    abbrev: str
    fields: list  # list of FieldDef
    category: Optional[str] = None
    source: Optional[str] = None


def parse_imc_xml(xml_path: str) -> dict[int, MessageDef]:
    """Parse IMC.xml and return a dict mapping message ID -> MessageDef."""
    tree = ET.parse(xml_path)
    root = tree.getroot()

    global_enums = {}
    for enum_def in root.findall(".//enumerations/def"):
        abbrev = enum_def.get("abbrev")
        values = {}
        for val in enum_def.findall("value"):
            vid = int(val.get("id"), 0)
            values[vid] = val.get("abbrev") or val.get("name")
        global_enums[abbrev] = values

    global_bitfields = {}
    for bf_def in root.findall(".//bitfields/def"):
        abbrev = bf_def.get("abbrev")
        values = {}
        for val in bf_def.findall("value"):
            vid = int(val.get("id"), 0)
            values[vid] = val.get("abbrev") or val.get("name")
        global_bitfields[abbrev] = values

    messages = {}
    for msg_elem in root.findall("message"):
        msg_id = int(msg_elem.get("id"))
        msg_name = msg_elem.get("name")
        msg_abbrev = msg_elem.get("abbrev")
        msg_category = msg_elem.get("category")
        msg_source = msg_elem.get("source")

        fields = []
        for field_elem in msg_elem.findall("field"):
            f_name = field_elem.get("name", "")
            f_abbrev = field_elem.get("abbrev", "")
            f_type = field_elem.get("type", "")
            f_unit = field_elem.get("unit")
            f_prefix = field_elem.get("prefix")
            f_msg_type = field_elem.get("message-type")

            enum_vals = {}
            bf_vals = {}

            if f_unit == "Enumerated":
                inline_values = field_elem.findall("value")
                if inline_values:
                    for v in inline_values:
                        vid = int(v.get("id"), 0)
                        enum_vals[vid] = v.get("abbrev") or v.get("name")
                elif f_type in global_enums:
                    enum_vals = global_enums[f_type]

            elif f_unit == "Bitfield":
                inline_values = field_elem.findall("value")
                if inline_values:
                    for v in inline_values:
                        vid = int(v.get("id"), 0)
                        bf_vals[vid] = v.get("abbrev") or v.get("name")
                elif f_type in global_bitfields:
                    bf_vals = global_bitfields[f_type]

            fields.append(FieldDef(
                name=f_name,
                abbrev=f_abbrev,
                type=f_type,
                unit=f_unit,
                enum_values=enum_vals,
                bitfield_values=bf_vals,
                message_type=f_msg_type,
                prefix=f_prefix,
            ))

        messages[msg_id] = MessageDef(
            id=msg_id,
            name=msg_name,
            abbrev=msg_abbrev,
            fields=fields,
            category=msg_category,
            source=msg_source,
        )

    return messages
