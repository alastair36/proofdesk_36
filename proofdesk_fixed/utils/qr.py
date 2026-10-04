"""
QR code generation, cross-platform (Windows / macOS / Linux).

Primary: the pure-Python `qrcode` package (listed in requirements.txt) - no system
libraries needed, works on Windows out of the box.
Fallback: the system libqrencode library via ctypes (Linux/macOS only), used only
if `qrcode` is not installed.

Per spec: the QR code encodes ONLY a public verification URL, never personal data.
"""
import os

try:
    import qrcode
    from qrcode.constants import ERROR_CORRECT_M
    _BACKEND = "qrcode"
except ImportError:  # pragma: no cover
    _BACKEND = "libqrencode"


def _generate_with_qrcode(text, out_path, box_size, border):
    qr = qrcode.QRCode(error_correction=ERROR_CORRECT_M, box_size=box_size, border=border)
    qr.add_data(text)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    img.save(out_path)


def _generate_with_libqrencode(text, out_path, box_size, border):
    import ctypes
    import ctypes.util
    from PIL import Image

    libname = ctypes.util.find_library("qrencode") or "libqrencode.so.4"
    try:
        lib = ctypes.CDLL(libname)
    except OSError as e:
        raise RuntimeError(
            "No QR backend available. Run: pip install -r requirements.txt"
        ) from e

    class _QRcode(ctypes.Structure):
        _fields_ = [("version", ctypes.c_int), ("width", ctypes.c_int),
                    ("data", ctypes.POINTER(ctypes.c_ubyte))]

    lib.QRcode_encodeString.restype = ctypes.POINTER(_QRcode)
    lib.QRcode_encodeString.argtypes = [ctypes.c_char_p, ctypes.c_int, ctypes.c_int,
                                        ctypes.c_int, ctypes.c_int]
    lib.QRcode_free.argtypes = [ctypes.POINTER(_QRcode)]

    qr_ptr = lib.QRcode_encodeString(text.encode("utf-8"), 0, 1, 2, 1)
    if not qr_ptr:
        raise RuntimeError("QR encoding failed")
    qr = qr_ptr.contents
    width = qr.width
    raw = ctypes.cast(qr.data, ctypes.POINTER(ctypes.c_ubyte * (width * width))).contents
    size = (width + 2 * border) * box_size
    img = Image.new("1", (size, size), 1)
    px = img.load()
    for y in range(width):
        for x in range(width):
            if raw[y * width + x] & 1:
                for dy in range(box_size):
                    for dx in range(box_size):
                        px[(x + border) * box_size + dx, (y + border) * box_size + dy] = 0
    lib.QRcode_free(qr_ptr)
    img.save(out_path)


def generate_qr_png(text, out_path, box_size=8, border=4):
    """Generate a QR PNG encoding `text` and save it to out_path."""
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    if _BACKEND == "qrcode":
        _generate_with_qrcode(text, out_path, box_size, border)
    else:
        _generate_with_libqrencode(text, out_path, box_size, border)
    return out_path
