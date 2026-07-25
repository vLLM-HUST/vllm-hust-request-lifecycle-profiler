from __future__ import annotations

import argparse
import os
from pathlib import Path

from pypdf import PdfReader
from pypdf import PdfWriter


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Rewrite a PDF without volatile creation metadata."
    )
    parser.add_argument("pdf", type=Path)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    pdf_path = args.pdf.resolve()
    reader = PdfReader(pdf_path)
    writer = PdfWriter()
    for page in reader.pages:
        writer.add_page(page)

    metadata = {
        key: value
        for key, value in (reader.metadata or {}).items()
        if key not in {"/CreationDate", "/ModDate"}
        and isinstance(key, str)
        and isinstance(value, str)
    }
    writer.metadata = None
    if metadata:
        writer.add_metadata(metadata)

    temporary_path = pdf_path.with_suffix(pdf_path.suffix + ".canonical.tmp")
    with temporary_path.open("wb") as handle:
        writer.write(handle)
    os.replace(temporary_path, pdf_path)


if __name__ == "__main__":
    main()
