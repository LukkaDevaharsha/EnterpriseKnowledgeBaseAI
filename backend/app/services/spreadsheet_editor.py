"""Validated cell editing for private CSV and XLSX documents."""

import csv
import io
import re
import zipfile

from app.services.document_processor import MAX_ROWS, _check_office_archive, _decode_text

MAX_EDITS = 2000
MAX_COLUMNS = 16384


class SpreadsheetEditError(ValueError):
    """Raised when a spreadsheet edit payload is invalid."""


def _cell_value(value, *, xlsx):
    if not isinstance(value, str):
        raise SpreadsheetEditError("Cell values must be text.")
    if not xlsx or value == "":
        return value if value else None
    if value.startswith("="):
        return value
    if value.lower() in {"true", "false"}:
        return value.lower() == "true"
    if len(value) == 1 or not (value.startswith("0") or value.startswith("-0")):
        if re.fullmatch(r"-?(?:0|[1-9]\d*)", value):
            try:
                return int(value)
            except ValueError:
                pass
        if re.fullmatch(r"-?(?:0|[1-9]\d*)\.\d+", value):
            try:
                return float(value)
            except ValueError:
                pass
    return value


def _validated_payload(payload, sheet_count, *, xlsx):
    if not isinstance(payload, dict):
        raise SpreadsheetEditError("An edit object is required.")
    changes = payload.get("changes", [])
    appended = payload.get("append_rows", [])
    if not isinstance(changes, list) or not isinstance(appended, list):
        raise SpreadsheetEditError("Spreadsheet changes must be arrays.")
    if len(changes) + len(appended) > MAX_EDITS:
        raise SpreadsheetEditError(f"A save can contain at most {MAX_EDITS} edits.")

    checked_changes = []
    for edit in changes:
        if not isinstance(edit, dict):
            raise SpreadsheetEditError("Each cell change must be an object.")
        sheet_index = edit.get("sheet_index")
        row_index = edit.get("row_index")
        column_index = edit.get("column_index")
        if (not all(isinstance(value, int) and not isinstance(value, bool) for value in (sheet_index, row_index, column_index))
                or not 0 <= sheet_index < sheet_count
                or not 0 <= row_index < MAX_ROWS
                or not 0 <= column_index < MAX_COLUMNS):
            raise SpreadsheetEditError("A cell position is outside the supported range.")
        value = _cell_value(edit.get("value"), xlsx=xlsx)
        checked_changes.append((sheet_index, row_index + 1, column_index + 1, value))

    checked_appends = []
    for row in appended:
        if not isinstance(row, dict) or not isinstance(row.get("values"), list):
            raise SpreadsheetEditError("Each added row must include a values array.")
        sheet_index = row.get("sheet_index")
        if not isinstance(sheet_index, int) or isinstance(sheet_index, bool) or not 0 <= sheet_index < sheet_count:
            raise SpreadsheetEditError("A worksheet index is invalid.")
        if len(row["values"]) > MAX_COLUMNS or any(not isinstance(value, str) for value in row["values"]):
            raise SpreadsheetEditError("An added row contains an invalid cell value.")
        checked_appends.append((sheet_index, [_cell_value(value, xlsx=xlsx) for value in row["values"]]))
    return checked_changes, checked_appends


def apply_spreadsheet_edits(content, file_type, payload):
    kind = (file_type or "").upper()
    if kind == "CSV":
        text = _decode_text(content)
        try:
            dialect = csv.Sniffer().sniff(text[:8192], delimiters=",\t;|")
        except csv.Error:
            dialect = csv.excel
        rows = list(csv.reader(io.StringIO(text), dialect))
        changes, appends = _validated_payload(payload, 1, xlsx=False)
        for sheet_index, row_index, column_index, value in changes:
            while len(rows) < row_index:
                rows.append([])
            row = rows[row_index - 1]
            while len(row) < column_index:
                row.append("")
            row[column_index - 1] = value or ""
        for sheet_index, values in appends:
            rows.append([value or "" for value in values])
        if len(rows) > MAX_ROWS:
            raise SpreadsheetEditError(f"A CSV file can contain at most {MAX_ROWS} rows.")
        output = io.StringIO(newline="")
        csv.writer(output, dialect=dialect).writerows(rows)
        encoded = output.getvalue().encode("utf-8-sig" if content.startswith((b"\xef\xbb\xbf", b"\xff\xfe", b"\xfe\xff")) else "utf-8")
    elif kind == "XLSX":
        names = _check_office_archive(content)
        if "xl/workbook.xml" not in names:
            raise SpreadsheetEditError("The XLSX workbook is invalid.")
        from openpyxl import load_workbook

        try:
            workbook = load_workbook(io.BytesIO(content), read_only=False, data_only=False, keep_links=False)
            changes, appends = _validated_payload(payload, len(workbook.worksheets), xlsx=True)
            for sheet_index, row_index, column_index, value in changes:
                workbook.worksheets[sheet_index].cell(row=row_index, column=column_index).value = value
            for sheet_index, values in appends:
                workbook.worksheets[sheet_index].append(values)
            if any(sheet.max_row > MAX_ROWS for sheet in workbook.worksheets):
                raise SpreadsheetEditError(f"An XLSX worksheet can contain at most {MAX_ROWS} rows.")
            output = io.BytesIO()
            workbook.save(output)
            workbook.close()
            encoded = output.getvalue()
        except SpreadsheetEditError:
            raise
        except (OSError, ValueError, RuntimeError, KeyError, zipfile.BadZipFile) as exc:
            raise SpreadsheetEditError("The XLSX workbook could not be updated.") from exc
    else:
        raise SpreadsheetEditError("Only CSV and XLSX files can be edited here.")
    if not encoded or len(encoded) > 10 * 1024 * 1024:
        raise SpreadsheetEditError("The updated spreadsheet exceeds the 10 MB limit.")
    return encoded
