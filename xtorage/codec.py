from __future__ import annotations

import hashlib
import json
import math
import os
import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from PIL import Image, ImageDraw


MAGIC = b"XTORAGE1"
HEADER_STRUCT = struct.Struct(">8sBBH16sIII32s32s")
HEADER_LEN = HEADER_STRUCT.size
PACKAGE_ROOT = Path(__file__).resolve().parent
DEFAULT_STEALTH_COVER = PACKAGE_ROOT / "assets" / "stealth_placeholder.png"


@dataclass(frozen=True)
class ModeSpec:
    name: str
    width: int
    height: int
    channels: tuple[int, ...]
    bits_per_channel: int
    image_mode: str
    base_rgba: tuple[int, int, int, int] | None = None
    visual_note: str = ""
    supports_cover_image: bool = False

    @property
    def capacity_bytes(self) -> int:
        return (self.width * self.height * len(self.channels) * self.bits_per_channel) // 8

    @property
    def max_payload_bytes(self) -> int:
        return self.capacity_bytes - HEADER_LEN


MODES: dict[str, ModeSpec] = {
    "rgba-alpha1-rgb-900": ModeSpec(
        name="rgba-alpha1-rgb-900",
        width=900,
        height=900,
        channels=(0, 1, 2),
        bits_per_channel=8,
        image_mode="RGBA",
        base_rgba=(255, 255, 255, 1),
        visual_note="confirmed Commerce PNG rehost; max composited delta 1 on white",
    ),
    "rgba-alpha1-rgb-800": ModeSpec(
        name="rgba-alpha1-rgb-800",
        width=800,
        height=800,
        channels=(0, 1, 2),
        bits_per_channel=8,
        image_mode="RGBA",
        base_rgba=(255, 255, 255, 1),
        visual_note="confirmed Commerce PNG rehost; max composited delta 1 on white",
    ),
    "rgba-alpha1-rgb-600": ModeSpec(
        name="rgba-alpha1-rgb-600",
        width=600,
        height=600,
        channels=(0, 1, 2),
        bits_per_channel=8,
        image_mode="RGBA",
        base_rgba=(255, 255, 255, 1),
        visual_note="confirmed Commerce PNG rehost; max composited delta 1 on white",
    ),
    "rgb-4lsb-600": ModeSpec("rgb-4lsb-600", 600, 600, (0, 1, 2), 4, "RGB", visual_note="confirmed, but visible delta can reach 15"),
    "rgb-3lsb-600": ModeSpec("rgb-3lsb-600", 600, 600, (0, 1, 2), 3, "RGB", visual_note="confirmed, but visible delta can reach 7"),
    "rgb-2lsb-600": ModeSpec("rgb-2lsb-600", 600, 600, (0, 1, 2), 2, "RGB", visual_note="confirmed; max channel delta 3"),
    "rgb-lsb-600": ModeSpec(
        "rgb-lsb-600",
        600,
        600,
        (0, 1, 2),
        1,
        "RGB",
        visual_note="confirmed; max channel delta 1",
        supports_cover_image=True,
    ),
    "red-lsb-600": ModeSpec(
        "red-lsb-600",
        600,
        600,
        (0,),
        1,
        "RGB",
        visual_note="confirmed; lowest capacity",
        supports_cover_image=True,
    ),
}

MODE_IDS = {name: index + 1 for index, name in enumerate(MODES)}
MODE_NAMES = {value: key for key, value in MODE_IDS.items()}
PROFILES = {
    "stealth": {
        "codec": "rgb-lsb-600",
        "description": "true LSB mode; changes each RGB channel by at most 1",
    },
    "max": {
        "codec": "rgba-alpha1-rgb-900",
        "description": "largest confirmed Commerce-safe capacity per image",
    },
}


def resolve_mode(name: str) -> str:
    if name in PROFILES:
        return PROFILES[name]["codec"]
    if name in MODES:
        return name
    raise ValueError(f"unknown mode/profile {name}")


@dataclass
class Frame:
    mode_name: str
    file_id: bytes
    chunk_index: int
    total_chunks: int
    payload: bytes
    payload_sha256: bytes
    file_sha256: bytes


def iter_bits(data: bytes) -> Iterable[int]:
    for byte in data:
        for shift in range(7, -1, -1):
            yield (byte >> shift) & 1


def bits_to_bytes(bits: list[int]) -> bytes:
    output = bytearray()
    for offset in range(0, len(bits), 8):
        value = 0
        for bit in bits[offset : offset + 8]:
            value = (value << 1) | bit
        output.append(value)
    return bytes(output)


def make_frame(mode_name: str, file_id: bytes, chunk_index: int, total_chunks: int, payload: bytes, file_sha256: bytes) -> bytes:
    mode_id = MODE_IDS[mode_name]
    payload_sha256 = hashlib.sha256(payload).digest()
    header = HEADER_STRUCT.pack(
        MAGIC,
        mode_id,
        0,
        HEADER_LEN,
        file_id,
        chunk_index,
        total_chunks,
        len(payload),
        payload_sha256,
        file_sha256,
    )
    return header + payload


def parse_frame(data: bytes) -> Frame:
    if len(data) < HEADER_LEN:
        raise ValueError("not enough data for Xtorage header")
    magic, mode_id, _flags, header_len, file_id, chunk_index, total_chunks, payload_len, payload_sha256, file_sha256 = HEADER_STRUCT.unpack(data[:HEADER_LEN])
    if magic != MAGIC:
        raise ValueError("missing XTORAGE1 magic")
    if mode_id not in MODE_NAMES:
        raise ValueError(f"unknown mode id {mode_id}")
    if header_len != HEADER_LEN:
        raise ValueError(f"unsupported header length {header_len}")
    end = header_len + payload_len
    if len(data) < end:
        raise ValueError("truncated Xtorage payload")
    payload = data[header_len:end]
    if hashlib.sha256(payload).digest() != payload_sha256:
        raise ValueError("payload sha256 mismatch")
    return Frame(MODE_NAMES[mode_id], file_id, chunk_index, total_chunks, payload, payload_sha256, file_sha256)


def fit_cover_image(path: Path, spec: ModeSpec) -> Image.Image:
    with Image.open(path) as source:
        img = source.convert(spec.image_mode)
    if img.width < spec.width or img.height < spec.height:
        raise ValueError(f"cover image must be at least {spec.width}x{spec.height}, got {img.width}x{img.height}")
    left = (img.width - spec.width) // 2
    top = (img.height - spec.height) // 2
    return img.crop((left, top, left + spec.width, top + spec.height))


def base_image(spec: ModeSpec, cover_image: Path | None = None) -> Image.Image:
    if cover_image is None and spec.supports_cover_image and DEFAULT_STEALTH_COVER.exists():
        cover_image = DEFAULT_STEALTH_COVER
    if cover_image:
        if not spec.supports_cover_image:
            raise ValueError(f"cover images are supported only by stealth/LSB codecs, not {spec.name}")
        return fit_cover_image(cover_image, spec)
    if spec.image_mode == "RGBA":
        assert spec.base_rgba is not None
        return Image.new("RGBA", (spec.width, spec.height), spec.base_rgba)
    img = Image.new("RGB", (spec.width, spec.height), (132, 166, 202))
    draw = ImageDraw.Draw(img)
    draw.rectangle((80, 80, spec.width - 80, spec.height - 80), outline=(20, 60, 120), width=6)
    draw.text((122, spec.height // 2 - 14), f"XTORAGE {spec.name}", fill=(20, 60, 120))
    return img


def encode_bits_to_image(img: Image.Image, frame: bytes, spec: ModeSpec) -> None:
    bits = list(iter_bits(frame))
    max_bits = spec.capacity_bytes * 8
    if len(bits) > max_bits:
        raise ValueError(f"frame too large: {len(bits)} bits > {max_bits} bits")

    pixels = img.load()
    mask = (1 << spec.bits_per_channel) - 1
    clear_mask = 0xFF ^ mask
    slots_per_pixel = len(spec.channels)
    for offset in range(0, len(bits), spec.bits_per_channel):
        group = bits[offset : offset + spec.bits_per_channel]
        value = 0
        for bit in group:
            value = (value << 1) | bit
        if len(group) < spec.bits_per_channel:
            value <<= spec.bits_per_channel - len(group)

        slot = offset // spec.bits_per_channel
        pixel_index = slot // slots_per_pixel
        channel = spec.channels[slot % slots_per_pixel]
        x = pixel_index % spec.width
        y = pixel_index // spec.width
        rgba = list(pixels[x, y])
        rgba[channel] = (rgba[channel] & clear_mask) | value
        pixels[x, y] = tuple(rgba)


def extract_bits_from_image(img: Image.Image, bit_count: int, spec: ModeSpec) -> list[int]:
    converted = img.convert(spec.image_mode)
    pixels = converted.load()
    bits: list[int] = []
    mask = (1 << spec.bits_per_channel) - 1
    slots_per_pixel = len(spec.channels)
    for index in range(bit_count):
        slot = index // spec.bits_per_channel
        bit_offset = index % spec.bits_per_channel
        pixel_index = slot // slots_per_pixel
        channel = spec.channels[slot % slots_per_pixel]
        x = pixel_index % converted.width
        y = pixel_index // converted.width
        value = pixels[x, y][channel] & mask
        bits.append((value >> (spec.bits_per_channel - bit_offset - 1)) & 1)
    return bits


def decode_image(path: Path, mode_name: str) -> Frame:
    spec = MODES[mode_name]
    with Image.open(path) as img:
        header = bits_to_bytes(extract_bits_from_image(img, HEADER_LEN * 8, spec))
        if header[: len(MAGIC)] != MAGIC:
            raise ValueError("missing XTORAGE1 magic")
        payload_len = HEADER_STRUCT.unpack(header)[7]
        frame_bytes = bits_to_bytes(extract_bits_from_image(img, (HEADER_LEN + payload_len) * 8, spec))
    frame = parse_frame(frame_bytes)
    if frame.mode_name != mode_name:
        raise ValueError(f"frame mode is {frame.mode_name}, expected {mode_name}")
    return frame


def detect_image_mode(path: Path) -> str:
    with Image.open(path) as img:
        for mode_name, spec in MODES.items():
            try:
                header = bits_to_bytes(extract_bits_from_image(img, HEADER_LEN * 8, spec))
                if header[: len(MAGIC)] != MAGIC:
                    continue
                mode_id = HEADER_STRUCT.unpack(header)[1]
                if MODE_NAMES.get(mode_id) == mode_name:
                    return mode_name
            except Exception:
                continue
    raise ValueError("could not detect Xtorage frame mode")


def decode_image_auto(path: Path) -> Frame:
    return decode_image(path, detect_image_mode(path))


def plan_file(input_path: Path, mode_name: str = "max", payload_size: int | None = None) -> dict:
    requested_mode = mode_name
    mode_name = resolve_mode(mode_name)
    spec = MODES[mode_name]
    file_size = input_path.stat().st_size
    chunk_payload_size = payload_size or spec.max_payload_bytes
    if chunk_payload_size > spec.max_payload_bytes:
        raise ValueError(f"payload size {chunk_payload_size} exceeds max {spec.max_payload_bytes}")
    chunks = max(1, math.ceil(file_size / chunk_payload_size))
    return {
        "input_path": str(input_path),
        "file_size": file_size,
        "requested_mode": requested_mode,
        "mode": mode_name,
        "mode_capacity_bytes": spec.capacity_bytes,
        "max_payload_bytes_per_image": spec.max_payload_bytes,
        "payload_bytes_per_image": chunk_payload_size,
        "images_needed": chunks,
        "visual_note": spec.visual_note,
    }


def encode_file(
    input_path: Path,
    out_dir: Path,
    mode_name: str = "max",
    payload_size: int | None = None,
    cover_image: Path | None = None,
) -> dict:
    requested_mode = mode_name
    mode_name = resolve_mode(mode_name)
    spec = MODES[mode_name]
    raw = input_path.read_bytes()
    file_sha256 = hashlib.sha256(raw).digest()
    file_id = os.urandom(16)
    chunk_payload_size = payload_size or spec.max_payload_bytes
    if chunk_payload_size > spec.max_payload_bytes:
        raise ValueError(f"payload size {chunk_payload_size} exceeds max {spec.max_payload_bytes}")

    out_dir.mkdir(parents=True, exist_ok=True)
    total_chunks = max(1, math.ceil(len(raw) / chunk_payload_size))
    chunks = []
    for index in range(total_chunks):
        payload = raw[index * chunk_payload_size : (index + 1) * chunk_payload_size]
        frame = make_frame(mode_name, file_id, index, total_chunks, payload, file_sha256)
        img = base_image(spec, cover_image)
        encode_bits_to_image(img, frame, spec)
        filename = f"{input_path.stem}.{index:04d}.{mode_name}.png"
        path = out_dir / filename
        img.save(path, optimize=True)
        chunks.append(
            {
                "index": index,
                "filename": filename,
                "path": str(path),
                "payload_size": len(payload),
                "image_size": path.stat().st_size,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "product_id": f"xtg{file_id.hex()[:12]}{index:04d}",
            }
        )

    manifest = {
        "version": 1,
        "requested_mode": requested_mode,
        "mode": mode_name,
        "file_id": file_id.hex(),
        "input_filename": input_path.name,
        "file_size": len(raw),
        "file_sha256": file_sha256.hex(),
        "payload_size": chunk_payload_size,
        "max_payload_bytes_per_image": spec.max_payload_bytes,
        "cover_image": str(cover_image) if cover_image else ("bundled:stealth_placeholder.png" if spec.supports_cover_image else None),
        "images_needed": total_chunks,
        "chunks": chunks,
    }
    manifest_path = out_dir / "manifest.json"
    manifest["manifest_path"] = str(manifest_path)
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


def decode_frames(frames: list[Frame], out_path: Path) -> dict:
    if not frames:
        raise ValueError("no frames supplied")
    file_id = frames[0].file_id
    total_chunks = frames[0].total_chunks
    file_sha256 = frames[0].file_sha256
    for frame in frames:
        if frame.file_id != file_id:
            raise ValueError("mixed file ids")
        if frame.total_chunks != total_chunks:
            raise ValueError("mixed total chunk counts")
        if frame.file_sha256 != file_sha256:
            raise ValueError("mixed file hashes")
    by_index = {frame.chunk_index: frame for frame in frames}
    missing = [index for index in range(total_chunks) if index not in by_index]
    if missing:
        raise ValueError(f"missing chunks: {missing}")
    payload = b"".join(by_index[index].payload for index in range(total_chunks))
    actual_sha256 = hashlib.sha256(payload).digest()
    if actual_sha256 != file_sha256:
        raise ValueError("file sha256 mismatch")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(payload)
    return {
        "file_id": file_id.hex(),
        "decoded_size": len(payload),
        "file_sha256": actual_sha256.hex(),
        "output_path": str(out_path),
    }


def decode_manifest(manifest_path: Path, out_path: Path | None = None, image_dir: Path | None = None) -> dict:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    mode_name = manifest["mode"]
    base_dir = image_dir or manifest_path.parent
    frames = []
    for chunk in sorted(manifest["chunks"], key=lambda item: item["index"]):
        path = Path(chunk.get("path", ""))
        if not path.exists():
            path = base_dir / chunk["filename"]
        frames.append(decode_image(path, mode_name))
    output = out_path or manifest_path.parent / manifest["input_filename"]
    return decode_frames(frames, output)
