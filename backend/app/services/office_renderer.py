"""Render Office presentation slides for the authorized study preview."""

import os
import re
import shutil
import subprocess
import tempfile
from functools import lru_cache
from io import BytesIO
from pathlib import Path

import pymupdf


class OfficeRendererUnavailable(RuntimeError):
    """Raised when LibreOffice is not installed in the backend runtime."""


class SlideRenderError(RuntimeError):
    """Raised when a presentation slide cannot be converted or rendered."""


def _office_binary():
    configured = os.getenv("LIBREOFFICE_PATH", "").strip()
    if configured:
        candidate = Path(configured)
        if candidate.is_file():
            return str(candidate)
        raise OfficeRendererUnavailable("LIBREOFFICE_PATH does not point to an executable file.")
    discovered = shutil.which("soffice") or shutil.which("libreoffice")
    if discovered:
        return discovered
    for base in (os.getenv("PROGRAMFILES"), os.getenv("PROGRAMFILES(X86)")):
        if base:
            candidate = Path(base) / "LibreOffice" / "program" / "soffice.exe"
            if candidate.is_file():
                return str(candidate)
    return None


@lru_cache(maxsize=16)
def _render_cached(content, page_number, scale, executable, query):
    with tempfile.TemporaryDirectory(prefix="ekb-pptx-render-") as temporary_directory:
        directory = Path(temporary_directory)
        input_path = directory / "presentation.pptx"
        output_path = directory / "presentation.pdf"
        profile_path = directory / "office-profile"
        input_path.write_bytes(content)

        try:
            result = subprocess.run(
                [
                    executable,
                    f"-env:UserInstallation={profile_path.as_uri()}",
                    "--headless",
                    "--convert-to", "pdf",
                    "--outdir", str(directory),
                    str(input_path),
                ],
                check=False,
                capture_output=True,
                text=True,
                timeout=60,
            )
        except subprocess.TimeoutExpired as exc:
            raise SlideRenderError("The presentation took too long to render.") from exc
        except OSError as exc:
            raise OfficeRendererUnavailable("LibreOffice could not be started.") from exc

        if result.returncode != 0 or not output_path.is_file():
            raise SlideRenderError("LibreOffice could not convert this presentation.")

        try:
            with pymupdf.open(output_path) as pdf:
                if page_number > pdf.page_count:
                    raise SlideRenderError("Slide number is outside the presentation.")
                page = pdf.load_page(page_number - 1)
                if query:
                    matches = page.search_for(query)
                    if not matches:
                        terms = list(dict.fromkeys(re.findall(r"[\w]+", query, flags=re.UNICODE)))
                        for term in terms[:20]:
                            if len(term) > 1:
                                matches.extend(page.search_for(term))
                    if matches:
                        highlight = page.add_highlight_annot(matches)
                        highlight.set_colors(stroke=(1, 0.78, 0.24))
                        highlight.set_opacity(0.45)
                        highlight.update()
                pixmap = page.get_pixmap(
                    matrix=pymupdf.Matrix(scale, scale), alpha=False
                )
                return pixmap.tobytes("png")
        except (pymupdf.FileDataError, pymupdf.FileNotFoundError,
                pymupdf.EmptyFileError, RuntimeError, ValueError) as exc:
            raise SlideRenderError("The converted slide could not be rendered.") from exc


def render_pptx_slide(content, page_number, scale=1.5, query=""):
    executable = _office_binary()
    if not executable:
        raise OfficeRendererUnavailable(
            "PPTX slide preview requires LibreOffice in the backend runtime."
        )
    if not isinstance(page_number, int) or page_number < 1:
        raise SlideRenderError("Slide number must be a positive integer.")
    if not 0.75 <= scale <= 3:
        raise SlideRenderError("Slide scale must be between 0.75 and 3.")
    return _render_cached(bytes(content), page_number, float(scale), executable, query.strip()[:2000])
