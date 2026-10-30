"""Small sample files for tests, built in memory (no binary files in the repo)."""

OSMOSIS_NOTES = (
    "Osmosis is the net movement of water molecules from a region of higher water potential\n"
    "to a region of lower water potential through a partially permeable membrane.\n"
    "Plant cells become turgid in a hypotonic solution because water enters the vacuole.\n"
    "Animal cells may burst in a hypotonic solution because they have no cell wall."
)


def make_pdf(text: str) -> bytes:
    """A valid one-page PDF showing `text` (one PDF line per line). Empty text = blank page."""
    ops = ["BT", "/F1 11 Tf", "50 780 Td", "14 TL"]
    for line in text.splitlines():
        escaped = line.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        ops.append(f"({escaped}) Tj T*")
    ops.append("ET")
    stream = "\n".join(ops).encode("latin-1")

    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents 4 0 R"
        b" /Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    pdf = bytearray(b"%PDF-1.4\n")
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(pdf))
        pdf += b"%d 0 obj\n" % number + body + b"\nendobj\n"
    xref_at = len(pdf)
    pdf += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    for offset in offsets:
        pdf += b"%010d 00000 n \n" % offset
    pdf += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (
        len(objects) + 1,
        xref_at,
    )
    return bytes(pdf)
