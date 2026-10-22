from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any

from .identity import ID_PATTERN
from .workspace import ContentToolError, Workspace, sha256_file, write_json


VERSION_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$")


def native_page_blocks(page: Any, page_index: int, source_key: str, source_version: str, source_hash: str, label: str | None = None) -> list[dict[str, Any]]:
    blocks = []
    text_blocks = [block for block in page.get_text("blocks", sort=True) if len(block) >= 7 and block[6] == 0 and block[4].strip()]
    for ordinal, block in enumerate(text_blocks, start=1):
        text = block[4].strip()
        bbox = [round(float(value), 3) for value in block[:4]]
        blocks.append({
            "bbox": bbox,
            "extractionMethod": "native-pymupdf",
            "id": f"{source_key}-{source_version}-p{page_index:04d}-b{ordinal:04d}".lower(),
            "locator": {"bbox": bbox, "physicalPageIndex": page_index, "printedPageLabel": label},
            "physicalPageIndex": page_index,
            "printedPageLabel": label,
            "sourceSha256": source_hash,
            "sourceVersion": source_version,
            "text": text,
            "textSha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        })
    return blocks


def _extraction_gate(workspace: Workspace, source: dict[str, Any]) -> None:
    policy = workspace.config.get("reviewPolicy", {})
    if policy.get("localSourceRightsConfirmed") is not True:
        raise ContentToolError("Set reviewPolicy.localSourceRightsConfirmed=true before extraction")
    rights = source.get("rights", {})
    if rights.get("localProcessingConfirmed") is not True:
        raise ContentToolError("The selected source has no confirmed local-processing right")


def extract_native_pdf(
    workspace: Workspace,
    source_key: str,
    source_version: str,
    pdf_path: str | Path,
) -> Path:
    if not ID_PATTERN.fullmatch(source_key):
        raise ContentToolError("Source key must use the stable ID syntax")
    if not VERSION_PATTERN.fullmatch(source_version):
        raise ContentToolError("Source version must be a safe stable label")
    inventory, source = workspace.source(source_key, source_version)
    _extraction_gate(workspace, source)
    source_file = Path(pdf_path).resolve()
    if not source_file.is_file():
        raise ContentToolError(f"Source PDF does not exist: {source_file}")
    source_hash = sha256_file(source_file)
    expected_hash = source.get("sha256")
    if expected_hash and expected_hash != source_hash:
        raise ContentToolError(f"Source hash changed for {source_key}@{source_version}; extraction stopped")
    try:
        import pymupdf
    except ImportError as error:
        raise ContentToolError("PyMuPDF is required for native PDF extraction; run uv sync") from error

    blocks: list[dict[str, Any]] = []
    printed_labels = source.get("printedPageLabels", {})
    try:
        document = pymupdf.open(source_file)
        if not document.is_pdf:
            raise ContentToolError(f"Source is not a PDF: {source_file}")
        for page_index, page in enumerate(document, start=1):
            label = printed_labels.get(str(page_index))
            blocks.extend(native_page_blocks(page, page_index, source_key, source_version, source_hash, label))
        page_count = document.page_count
    except ContentToolError:
        raise
    except Exception as error:
        raise ContentToolError(f"Cannot extract PDF {source_file}: {error}") from error
    finally:
        if "document" in locals():
            document.close()

    if not blocks:
        raise ContentToolError("PDF contains no native text blocks; OCR/layout review is required")
    if sha256_file(source_file) != source_hash:
        raise ContentToolError("Source PDF changed during extraction; no artifact was written")
    output = workspace.inside("extracts", source_key, f"{source_version}.native.json")
    write_json(
        output,
        {
            "blocks": blocks,
            "extractionMethod": "native-pymupdf",
            "fileName": source_file.name,
            "pageCount": page_count,
            "sourceKey": source_key,
            "sourceSha256": source_hash,
            "sourceVersion": source_version,
        },
    )
    if not expected_hash:
        source["sha256"] = source_hash
        write_json(workspace.inventory_path, inventory)
    return output
