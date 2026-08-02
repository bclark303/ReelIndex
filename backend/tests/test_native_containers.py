import struct

from app.services.container_native import (
    NativeSample,
    parse_avi,
    parse_asf,
    parse_iso_bmff,
    parse_mpeg_ps,
    parse_mpeg_ts,
    ASF_AUDIO_MEDIA,
    ASF_FILE_PROPERTIES,
    ASF_HEADER,
    ASF_STREAM_PROPERTIES,
    ASF_VIDEO_MEDIA,
)


def atom(kind: str, payload: bytes) -> bytes:
    return struct.pack(">I4s", len(payload) + 8, kind.encode("latin-1")) + payload


def fullbox(body: bytes, version: int = 0) -> bytes:
    return bytes([version, 0, 0, 0]) + body


def mp4_track(handler: bytes, entry: bytes, duration: int = 900000, timescale: int = 90000) -> bytes:
    mdhd = atom("mdhd", fullbox(struct.pack(">IIIIHH", 0, 0, timescale, duration, 0x15C7, 0)))
    hdlr = atom("hdlr", fullbox(struct.pack(">I4s", 0, handler) + b"\0" * 12))
    stsd = atom("stsd", fullbox(struct.pack(">I", 1) + entry))
    stts = atom("stts", fullbox(struct.pack(">III", 1, 240, 3750)))
    stbl = atom("stbl", stsd + stts)
    return atom("trak", atom("mdia", mdhd + hdlr + atom("minf", stbl)))


def test_native_mp4_parser_reads_head_or_tail_moov():
    video_payload = bytearray(78)
    struct.pack_into(">H", video_payload, 24, 1920)
    struct.pack_into(">H", video_payload, 26, 1080)
    struct.pack_into(">H", video_payload, 74, 24)
    video_entry = atom("avc1", bytes(video_payload))
    audio_payload = bytearray(28)
    struct.pack_into(">H", audio_payload, 16, 6)
    struct.pack_into(">H", audio_payload, 18, 16)
    struct.pack_into(">I", audio_payload, 24, 48000 << 16)
    audio_entry = atom("mp4a", bytes(audio_payload))
    mvhd = atom("mvhd", fullbox(struct.pack(">IIII", 0, 0, 1000, 10000) + b"\0" * 80))
    moov = atom("moov", mvhd + mp4_track(b"vide", video_entry) + mp4_track(b"soun", audio_entry))
    result = parse_iso_bmff(NativeSample(head=atom("ftyp", b"isom\0\0\0\0"), tail=moov, source_size=100_000_000), ".mp4")
    assert result["container"] == "mp4"
    assert result["duration_seconds"] == 10
    assert result["video_codec"] == "h264"
    assert result["width"] == 1920
    assert result["height"] == 1080
    assert result["audio_codec"] == "aac"
    assert result["audio_channels"] == 6.0
    assert round(result["extended"]["frame_rate"], 2) == 24.0


def chunk(kind: bytes, payload: bytes) -> bytes:
    out = kind + struct.pack("<I", len(payload)) + payload
    return out + (b"\0" if len(payload) & 1 else b"")


def list_chunk(kind: bytes, payload: bytes) -> bytes:
    return chunk(b"LIST", kind + payload)


def test_native_avi_parser_reads_stream_headers():
    avih = bytearray(56)
    struct.pack_into("<I", avih, 0, 41667)
    struct.pack_into("<I", avih, 16, 240)
    struct.pack_into("<I", avih, 24, 2)
    struct.pack_into("<II", avih, 32, 1920, 1080)
    vstrh = bytearray(56)
    vstrh[0:4] = b"vids"; vstrh[4:8] = b"H264"
    struct.pack_into("<III", vstrh, 20, 1, 24, 0)
    struct.pack_into("<I", vstrh, 32, 240)
    vstrf = bytearray(40)
    struct.pack_into("<IiiHH4s", vstrf, 0, 40, 1920, 1080, 1, 24, b"H264")
    astrh = bytearray(56)
    astrh[0:4] = b"auds"
    struct.pack_into("<III", astrh, 20, 1, 48000, 0)
    struct.pack_into("<I", astrh, 32, 480000)
    astrf = struct.pack("<HHIIHH", 0x00FF, 6, 48000, 24000, 1, 16)
    hdrl = list_chunk(b"hdrl", chunk(b"avih", bytes(avih)) + list_chunk(b"strl", chunk(b"strh", bytes(vstrh)) + chunk(b"strf", bytes(vstrf))) + list_chunk(b"strl", chunk(b"strh", bytes(astrh)) + chunk(b"strf", astrf)))
    riff = b"RIFF" + struct.pack("<I", len(hdrl) + 4) + b"AVI " + hdrl
    result = parse_avi(NativeSample(head=riff, source_size=50_000_000))
    assert result["video_codec"] == "h264"
    assert result["width"] == 1920
    assert result["audio_codec"] == "aac"
    assert result["audio_channels"] == 6.0


def asf_object(guid: bytes, payload: bytes) -> bytes:
    return guid + struct.pack("<Q", len(payload) + 24) + payload


def test_native_asf_parser_reads_wmv_and_wma():
    file_props = bytearray(80)
    struct.pack_into("<Q", file_props, 40, 120 * 10_000_000)
    struct.pack_into("<Q", file_props, 56, 0)
    struct.pack_into("<I", file_props, 76, 8_000_000)
    bitmap = bytearray(40)
    struct.pack_into("<IiiHH4s", bitmap, 0, 40, 1280, 720, 1, 24, b"WMV3")
    video_specific = struct.pack("<IIBH", 1280, 720, 0, len(bitmap)) + bitmap
    video_payload = ASF_VIDEO_MEDIA + b"\0" * 16 + struct.pack("<QIIHI", 0, len(video_specific), 0, 1, 0) + video_specific
    audio_specific = struct.pack("<HHIIHH", 0x0161, 2, 48000, 24000, 1, 16)
    audio_payload = ASF_AUDIO_MEDIA + b"\0" * 16 + struct.pack("<QIIHI", 0, len(audio_specific), 0, 2, 0) + audio_specific
    objects = asf_object(ASF_FILE_PROPERTIES, bytes(file_props)) + asf_object(ASF_STREAM_PROPERTIES, video_payload) + asf_object(ASF_STREAM_PROPERTIES, audio_payload)
    header = ASF_HEADER + struct.pack("<QI", len(objects) + 30, 3) + b"\x01\x02" + objects
    result = parse_asf(NativeSample(head=header, source_size=120_000_000))
    assert result["duration_seconds"] == 120
    assert result["video_codec"] == "wmv3"
    assert result["width"] == 1280
    assert result["audio_codec"] == "wmav2"
    assert result["audio_channels"] == 2.0


def encode_pts(value: int) -> bytes:
    return bytes([
        0x20 | (((value >> 30) & 7) << 1) | 1,
        (value >> 22) & 0xFF,
        (((value >> 15) & 0x7F) << 1) | 1,
        (value >> 7) & 0xFF,
        ((value & 0x7F) << 1) | 1,
    ])


def ts_packet(pid: int, payload: bytes, pusi: bool = True) -> bytes:
    header = bytes([0x47, (0x40 if pusi else 0) | ((pid >> 8) & 0x1F), pid & 0xFF, 0x10])
    return (header + payload + b"\xff" * 188)[:188]


def ts_sample(pts: int) -> bytes:
    pat = bytes([0]) + bytes([0x00, 0xB0, 0x0D, 0, 1, 0xC1, 0, 0, 0, 1, 0xE1, 0x00, 0, 0, 0, 0])
    pmt = bytes([0]) + bytes([0x02, 0xB0, 0x17, 0, 1, 0xC1, 0, 0, 0xE1, 0x01, 0xF0, 0, 0x1B, 0xE1, 0x01, 0xF0, 0, 0x81, 0xE1, 0x02, 0xF0, 0, 0, 0, 0, 0])
    pes = b"\x00\x00\x01\xe0" + b"\x00\x20" + b"\x80\x80\x05" + encode_pts(pts) + b"\x00\x00\x01\x67\x42\x00\x1e\xf4\x05\x01\xed\x00\xf0\x88\x45\x80"
    null = ts_packet(0x1FFF, b"", False)
    return ts_packet(0, pat) + ts_packet(0x100, pmt) + ts_packet(0x101, pes) + null + null


def test_native_transport_parser_reads_program_and_duration():
    result = parse_mpeg_ts(NativeSample(head=ts_sample(90_000), tail=ts_sample(990_000), source_size=10_000_000))
    assert result["container"] == "mpegts"
    assert result["duration_seconds"] == 10
    assert result["video_codec"] == "h264"
    assert result["audio_codec"] == "ac3"


def ps_pes(pts: int) -> bytes:
    payload = b"\x80\x80\x05" + encode_pts(pts) + b"\x00\x00\x01\xb3\x2d\x02\x40\x34"
    return b"\x00\x00\x01\xe0" + struct.pack(">H", len(payload)) + payload


def test_native_program_stream_parser_reads_sequence_header():
    head = b"\x00\x00\x01\xba" + b"\0" * 10 + ps_pes(90_000)
    tail = b"\x00\x00\x01\xba" + b"\0" * 10 + ps_pes(540_000)
    result = parse_mpeg_ps(NativeSample(head=head, tail=tail, source_size=10_000_000))
    assert result["duration_seconds"] == 5
    assert result["video_codec"] == "mpeg2video"
    assert result["width"] == 720
    assert result["height"] == 576
