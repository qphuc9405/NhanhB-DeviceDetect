"""Only Probe Request, status and channel records; reject logs and unrelated nodes."""
import re
from typing import Annotated, Literal
from pydantic import BaseModel, Field, TypeAdapter, field_validator

def mac_valid(value):return bool(re.fullmatch(r'[0-9a-fA-F]{2}(:[0-9a-fA-F]{2}){5}',value))
class Wire(BaseModel):
    v: Literal[1]
    type: str
    node: Literal['sniffer']
    boot_id: str = Field(min_length=1,max_length=40)
    ts_us: int = Field(ge=0,strict=True)
    seq: int = Field(ge=0,strict=True)
    @field_validator('boot_id')
    @classmethod
    def nonempty(cls,v):
        if not v.strip():raise ValueError('empty boot ID')
        return v
class Probe(Wire):
    type: Literal['probe']
    source_mac: str
    rssi: int = Field(ge=-127,le=0,strict=True)
    channel: int = Field(ge=1,le=13,strict=True)
    frame_seq: int = Field(ge=0,le=4095,strict=True)
    retry: bool = False
    # Danh sách 'mã:độ dài' của Information Element theo thứ tự trong khung; rỗng với firmware cũ
    ie: str = Field(default='',max_length=200,pattern=r'^(\d{1,3}:\d{1,3}(,\d{1,3}:\d{1,3})*)?$')
class Status(Wire):
    type: Literal['status']
    capture_active: bool
    own_mac: str
    channel: int = Field(ge=1,le=13)
    probe_seen: int = Field(ge=0)
    probe_dropped: int = Field(ge=0)
    invalid: int = Field(ge=0)
    serial_errors: int = Field(ge=0)
    bytes_written: int = Field(ge=0)
    serial_baud: Literal[460800]
    sniffer_enabled: bool
    scan_mode: Literal['fixed','hopping']
    dwell_ms: int = Field(ge=100,le=10000)
class Channel(Wire):
    type: Literal['channel']
    channel: int = Field(ge=1,le=13)
    dwell_ms: int = Field(ge=100,le=10000)
adapter=TypeAdapter(Annotated[Probe|Status|Channel,Field(discriminator='type')])
def parse_line(line):
    if len(line)>16000:raise ValueError('oversized record')
    try:p=adapter.validate_json(line).model_dump()
    except Exception as e:raise ValueError('invalid sniffer record') from e
    for key in ['source_mac','own_mac']:
        if key in p:
            if not mac_valid(p[key]):raise ValueError('invalid MAC')
            p[key]=p[key].lower()
    return p
