"""Tiny test images built in code (no files needed)."""
import base64
import struct
import zlib


def png(width: int = 2, height: int = 2, rgb: tuple[int, int, int] = (255, 0, 0)) -> bytes:
    """A real, valid solid-color PNG."""

    def chunk(kind: bytes, body: bytes) -> bytes:
        return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body))

    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)  # 8-bit RGB
    rows = b"".join(b"\x00" + bytes(rgb) * width for _ in range(height))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header)
            + chunk(b"IDAT", zlib.compress(rows)) + chunk(b"IEND", b""))


# Signature-only samples: enough for type detection (never sent to a real model in tests).
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 16
GIF = b"GIF89a" + b"\x00" * 16
WEBP = b"RIFF\x00\x00\x00\x00WEBPVP8 " + b"\x00" * 8
PDF = b"%PDF-1.7\n" + b"\x00" * 16


def b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")
