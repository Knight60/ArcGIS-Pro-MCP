# -*- coding: utf-8 -*-
"""Metadata records (ISO 19139): read, edit, export and batch-apply from tables.

Contributed by Danny Benavides.
"""

import csv
import os
import zipfile
import xml.etree.ElementTree as ET

import arcpy

from .common import resolve_path
from .registry import command

GROUP = "metadata"

# Spanish form field -> arcpy.metadata.Metadata attribute. The English and
# camelCase spellings (title, access_constraints, accessConstraints...) are
# accepted as-is.
FIELD_ALIASES = {
    "titulo": "title",
    "resumen": "summary",
    "descripcion": "description",
    "etiquetas": "tags",
    "creditos": "credits",
    "restricciones_acceso": "accessConstraints",
    "limitaciones_uso": "useLimitations",
}

ATTRS = ("title", "summary", "description", "tags", "credits",
         "accessConstraints", "useLimitations")

VALID_KEYS = set(FIELD_ALIASES) | set(ATTRS) | {"access_constraints",
                                                "use_limitations"}

STYLE_CANDIDATES = ("ISO19139", "ISO 19139",
                    "ISO 19139 Metadata Implementation Specification GML3.2")


def _normalize_field(key):
    """Spanish, English or camelCase field name -> arcpy metadata attribute."""
    attr = FIELD_ALIASES.get(key)
    if attr is None:
        attr = key.replace("_constraints", "Constraints") \
                  .replace("_limitations", "Limitations")
    return attr


def _metadata(source):
    if not arcpy.Exists(source):
        raise ValueError("Dataset does not exist: {}".format(source))
    return arcpy.metadata.Metadata(source)


def _current_style(md):
    try:
        return getattr(md, "metadataStyle", None) or getattr(md, "style", None) \
            or "?"
    except Exception:
        return "?"


def _ensure_iso19139(md):
    """Upgrade the record to ISO 19139, trying every spelling Pro accepts."""
    for candidate in STYLE_CANDIDATES:
        try:
            md.upgrade(candidate)
            return candidate
        except Exception:
            continue
    raise RuntimeError("No ISO 19139 style was accepted by ArcGIS Pro.")


def _apply_fields(md, fields):
    applied = []
    for key, value in fields.items():
        if key not in VALID_KEYS or value in (None, ""):
            continue
        setattr(md, _normalize_field(key), str(value))
        applied.append(key)
    return applied


@command("get_metadata", GROUP)
def get_metadata(params):
    """Read a dataset's metadata record: the current metadata style plus
    title, summary, description, tags, credits, access constraints and use
    limitations."""
    source = resolve_path(params["source"])
    md = _metadata(source)
    out = {"source": source, "style": _current_style(md)}
    for attr in ATTRS:
        try:
            out[attr] = getattr(md, attr) or ""
        except Exception:
            out[attr] = ""
    return out


@command("set_metadata", GROUP)
def set_metadata(params):
    """Write metadata fields on a dataset or geodatabase, optionally upgrading
    the record to the ISO 19139 style first. Field names may be given in
    English or Spanish."""
    source = resolve_path(params["source"])
    fields = params.get("fields") or {}
    if not fields:
        raise ValueError("fields is required (dict of metadata field -> value)")
    md = _metadata(source)
    applied_style = None
    if params.get("estilo_iso19139", True):
        applied_style = _ensure_iso19139(md)
    applied = _apply_fields(md, fields)
    unknown = sorted(set(fields) - VALID_KEYS)
    md.save()
    out = {"source": source, "applied_fields": applied}
    if applied_style:
        out["style"] = applied_style
    if unknown:
        out["unknown_fields_ignored"] = unknown
    return out


@command("export_metadata_iso19139", GROUP)
def export_metadata_iso19139(params):
    """Export a dataset's metadata record to an ISO 19139 XML file."""
    source = resolve_path(params["source"])
    out_path = resolve_path(params["out_path"])
    md = _metadata(source)
    parent = os.path.dirname(out_path) or "."
    if not os.path.isdir(parent):
        os.makedirs(parent)
    md.exportMetadata(out_path, "ISO19139")
    if not os.path.isfile(out_path):
        raise RuntimeError("exportMetadata did not create the file -- check "
                           "the path")
    return {"source": source, "file": out_path, "style": "ISO19139"}


# --- CSV / XLSX reference tables (stdlib only, no extra dependencies) --------

def _read_rows(table_path):
    suffix = os.path.splitext(table_path)[1].lower()
    if suffix == ".csv":
        with open(table_path, encoding="utf-8-sig") as handle:
            rows = list(csv.reader(handle))
        return _rows_to_dicts(rows)
    if suffix == ".xlsx":
        return _read_xlsx(table_path)
    raise ValueError("Unsupported table format: {} (use .csv or .xlsx)"
                     .format(table_path))


def _rows_to_dicts(rows):
    if not rows:
        return []
    headers = [str(c).strip() for c in rows[0]]
    out = []
    for row in rows[1:]:
        if not any(str(c).strip() for c in row):
            continue
        record = {}
        for index, header in enumerate(headers):
            record[header] = str(row[index]).strip() if index < len(row) else ""
        out.append(record)
    return out


def _read_xlsx(path):
    """First sheet of an .xlsx, values only, using nothing but the stdlib."""
    with zipfile.ZipFile(path) as archive:
        shared = []
        try:
            root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
            ns = {"m": "http://schemas.openxmlformats.org/"
                      "spreadsheetml/2006/main"}
            for si in root.findall("m:si", ns):
                shared.append("".join(t.text or "" for t in si.iter()
                                      if t.tag.endswith("}t")))
        except KeyError:
            pass
        sheets = [n for n in archive.namelist()
                  if n.startswith("xl/worksheets/") and n.endswith(".xml")]
        if not sheets:
            return []
        root = ET.fromstring(archive.read(sorted(sheets)[0]))
        ns = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
        rows = []
        for row in root.findall(".//m:sheetData/m:row", ns):
            cells = []
            for cell in row.findall("m:c", ns):
                cell_type = cell.get("t", "")
                value = cell.find("m:v", ns)
                text = ""
                if cell_type == "s" and value is not None:
                    text = shared[int(value.text)]
                elif cell_type == "inlineStr":
                    inline = cell.find("m:is", ns)
                    if inline is not None:
                        text = "".join(x.text or "" for x in inline.iter()
                                       if x.tag.endswith("}t"))
                elif value is not None:
                    text = value.text or ""
                cells.append(text)
            rows.append(cells)
    return _rows_to_dicts(rows)


def _plans_from_rows(rows, source):
    """Table rows -> list of (dataset, fields) application plans.

    Recognised shapes: a campo|valor form for one dataset (pass 'source'), a
    batch table with a dataset column plus one metadata column per field, a
    single form row whose columns are all metadata fields, or a plain
    two-column field|value table.
    """
    if not rows:
        raise ValueError("The table has no data rows.")
    headers = list(rows[0].keys())
    lowered = {h.lower() for h in headers}
    if "campo" in lowered and "valor" in lowered:
        if not source:
            raise ValueError("This table is a campo|valor form -- pass "
                             "'source'.")
        fields = {row["campo"]: row["valor"] for row in rows if row.get("campo")}
        return [(source, fields)]
    if lowered & {"dataset", "ruta", "fuente", "fuente_datos", "capa"}:
        column = next(h for h in headers
                      if h.lower() in {"dataset", "ruta", "fuente",
                                       "fuente_datos", "capa"})
        plans = []
        for row in rows:
            if not row.get(column):
                continue
            fields = {k: v for k, v in row.items() if k != column and v}
            plans.append((row[column], fields))
        return plans
    if all(c.lower() in VALID_KEYS for c in headers):
        if not source:
            raise ValueError("This table is a metadata form -- pass 'source'.")
        return [(source, rows[0])]
    if len(headers) < 2:
        raise ValueError("Unrecognised table shape.")
    if not source:
        raise ValueError("This table is a field|value form -- pass 'source'.")
    fields = {row[headers[0]]: row[headers[1]] for row in rows
              if row.get(headers[0])}
    return [(source, fields)]


@command("set_metadata_from_table", GROUP)
def set_metadata_from_table(params):
    """Apply metadata to one or many datasets from a CSV/XLSX reference table.

    Two shapes are recognised: a campo|valor form for a single dataset (pass
    'source'), and a batch table with a dataset column plus one metadata
    column per field.
    """
    table_path = resolve_path(params["table_path"])
    if not os.path.isfile(table_path):
        raise ValueError("Table not found: {}".format(table_path))
    source = resolve_path(params.get("source") or "")
    upgrade = params.get("estilo_iso19139", True)
    plans = _plans_from_rows(_read_rows(table_path), source)
    results = []
    for dataset, fields in plans:
        entry = {"source": dataset}
        try:
            md = _metadata(dataset)
            if upgrade:
                entry["style"] = _ensure_iso19139(md)
            entry["applied_fields"] = _apply_fields(md, fields)
            md.save()
        except Exception as exc:
            entry["error"] = "{}: {}".format(type(exc).__name__, exc)
        results.append(entry)
    return {"table": table_path, "datasets": len(results), "results": results}
