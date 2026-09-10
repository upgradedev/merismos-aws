"""Bounded, read-only CSV review using the same intake rules as the writer."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import re

from . import intake

MAX_BYTES = 65_536
MAX_ROWS = 50
REQUIRED = ("title", "donor", "quantity", "unit", "category", "collection_date")
OPTIONAL = ("use_by", "allergens", "allergens_unknown", "hours_unrefrigerated", "note")
FIELDS = REQUIRED + OPTIONAL


def signature(offer: dict) -> str:
    """Compare all intake facts; identifiers and coordinator labels are not facts."""
    value = {k: offer.get(k) for k in FIELDS if k != "allergens_unknown"}
    # A fixture and an intake use the same numeric values and allergen ordering.
    value["quantity"] = float(value["quantity"])
    if value["hours_unrefrigerated"] is not None:
        value["hours_unrefrigerated"] = float(value["hours_unrefrigerated"])
    if isinstance(value["allergens"], list):
        value["allergens"] = sorted(value["allergens"])
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def strict_form(form: dict) -> dict:
    for key, value in form.items():
        if key not in FIELDS or not isinstance(value, str):
            raise intake.Rejected("Every CSV field must be text in the documented schema.")
        if value.lstrip().startswith(("=", "+", "-", "@")):
            raise intake.Rejected(f"{key}: spreadsheet formula-like values are refused.")
        if any(ord(c) < 32 and c not in "\r\n\t" for c in value):
            raise intake.Rejected(f"{key}: control characters are not allowed.")
    for key, limit in (("title", 120), ("donor", 120), ("note", 600), ("allergens", 200)):
        if len(form.get(key, "")) > limit:
            raise intake.Rejected(f"{key}: maximum {limit} characters; nothing was truncated.")
    for key in REQUIRED:
        if not form.get(key, "").strip():
            raise intake.Rejected(f"{key}: a value is required.")
    for key in ("collection_date", "use_by"):
        if form.get(key) and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", form[key]):
            raise intake.Rejected(f"{key}: use an exact YYYY-MM-DD date.")
    if not re.fullmatch(r"\d+(?:\.\d{1,2})?", form["quantity"].strip()):
        raise intake.Rejected("quantity: use a positive decimal with at most two decimal places.")
    if form["unit"] not in intake.UNITS or form["category"] not in intake.CATEGORIES:
        raise intake.Rejected("unit/category: use an exact value from the schema.")
    unknown = form.get("allergens_unknown", "").strip().lower()
    if unknown not in ("", "true", "false"):
        raise intake.Rejected("allergens_unknown: use true or false, or leave empty for unknown.")
    if unknown != "false" and form.get("allergens", "").strip():
        raise intake.Rejected("allergens: declare allergens_unknown=false to supply a list.")
    hours = form.get("hours_unrefrigerated", "").strip()
    if hours and not re.fullmatch(r"\d+(?:\.\d)?", hours):
        raise intake.Rejected("hours_unrefrigerated: use a decimal with at most one decimal place.")
    if hours and form["category"] not in ("chilled", "frozen"):
        raise intake.Rejected("hours_unrefrigerated: only applies to chilled or frozen food.")
    normalized = {**form, "allergens_unknown": unknown != "false"}
    offer = intake.offer_from_form(normalized, "preview")
    intake._refuse_a_person(form.get("allergens", ""))
    intake._refuse_an_instruction(form.get("allergens", ""))
    return offer


def preview(text: str, existing: list[dict]) -> dict:
    if not isinstance(text, str) or len(text.encode("utf-8")) > MAX_BYTES:
        raise intake.Rejected(f"CSV must be UTF-8 text, at most {MAX_BYTES} bytes.")
    if "\ufffd" in text:
        raise intake.Rejected("CSV contains invalid UTF-8 replacement characters. Export UTF-8 again.")
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    reader = csv.reader(io.StringIO(text.removeprefix("\ufeff"), newline=""), strict=True)
    try:
        header = next(reader, [])
        if len(header) != len(set(header)) or not set(REQUIRED) <= set(header) or (
            set(header) - set(FIELDS)
        ):
            raise intake.Rejected("CSV header must contain each required field once, "
                                  "with only the documented optional fields.")
        rows, seen = [], {}
        known = {signature(o): o["id"] for o in existing}
        for number, cells in enumerate(reader, 2):
            if len(rows) >= MAX_ROWS:
                raise intake.Rejected(f"CSV exceeds {MAX_ROWS} data rows. Split the file.")
            row = {"number": number, "status": "invalid", "detail": "", "offer": None}
            try:
                if len(cells) != len(header):
                    raise intake.Rejected("Column count differs from the header.")
                form = dict(zip(header, cells, strict=True))
                offer = strict_form(form)
                key = signature(offer)
                if key in seen:
                    row.update(status="duplicate", detail=f"Duplicate of CSV row {seen[key]}.")
                elif key in known:
                    row.update(status="duplicate", detail=f"Already filed as {known[key]}.")
                else:
                    row.update(status="valid", offer=offer, detail="Valid intake; not a safety approval.")
                seen.setdefault(key, number)
            except intake.Rejected as error:
                row["detail"] = str(error)
            rows.append(row)
    except csv.Error as error:
        raise intake.Rejected(f"Malformed CSV near line {reader.line_num}: {error}.") from None
    if not rows:
        raise intake.Rejected("CSV has no data rows.")
    return {"digest": digest, "rows": rows, "max_bytes": MAX_BYTES, "max_rows": MAX_ROWS}


def selected_form(text: str, number: int, digest: str, existing: list[dict]) -> dict:
    reviewed = preview(text, existing)
    if reviewed["digest"] != digest:
        raise intake.Rejected("CSV bytes changed since preview. Preview the file again.")
    row = next((r for r in reviewed["rows"] if type(number) is int and r["number"] == number), None)
    if row is None or row["status"] != "valid":
        raise intake.Rejected(row["detail"] if row else "Select a valid CSV data row.")
    reader = csv.DictReader(io.StringIO(text.removeprefix("\ufeff"), newline=""), strict=True)
    form = next(form for index, form in enumerate(reader, 2) if index == number)
    return {**form, "allergens_unknown": form.get("allergens_unknown", "").lower() != "false"}
