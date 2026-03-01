#!/usr/bin/env python
"""Read back a filled test form PDF and display extracted field values.

Use this after filling out boox_form_test.pdf on your Boox and syncing back.

Usage:
    python tests/read_test_form.py [path_to_filled_pdf]

If no path given, looks for tests/output/boox_form_test.pdf
"""

import sys
from pathlib import Path

from pypdf import PdfReader


def main():
    if len(sys.argv) > 1:
        pdf_path = sys.argv[1]
    else:
        pdf_path = str(Path(__file__).parent / "output" / "boox_form_test.pdf")

    if not Path(pdf_path).exists():
        print(f"File not found: {pdf_path}")
        print("Generate it first: python tests/generate_test_form.py")
        return

    reader = PdfReader(pdf_path)

    print(f"Reading: {pdf_path}")
    print(f"Pages: {len(reader.pages)}")
    print()

    # Method 1: get_form_text_fields (text fields only)
    text_fields = reader.get_form_text_fields()
    print("═" * 50)
    print("  Text Fields (get_form_text_fields)")
    print("═" * 50)
    if text_fields:
        for name, value in text_fields.items():
            status = "FILLED" if value else "empty"
            print(f"  {name}: {repr(value)} [{status}]")
    else:
        print("  (none found)")

    # Method 2: get_fields (all fields including checkboxes/radios)
    all_fields = reader.get_fields()
    print()
    print("═" * 50)
    print("  All Fields (get_fields)")
    print("═" * 50)
    if all_fields:
        for name, field_obj in all_fields.items():
            if isinstance(field_obj, dict):
                value = field_obj.get("/V", "(no value)")
                field_type = field_obj.get("/FT", "unknown")
                print(f"  {name}:")
                print(f"    Type: {field_type}")
                print(f"    Value: {repr(value)}")
            else:
                print(f"  {name}: {repr(field_obj)}")
    else:
        print("  (none found)")

    # Summary
    print()
    print("═" * 50)
    print("  Validation Summary")
    print("═" * 50)

    checks = {
        "Checkbox (was_read)": "was_read" in (all_fields or {}),
        "Radio (rating)": "rating" in (all_fields or {}),
        "Text (topic)": "topic" in (text_fields or {}),
        "Multiline (liked)": "liked" in (text_fields or {}),
        "Radio (want_more)": "want_more" in (all_fields or {}),
        "Checkboxes (tags)": any(k.startswith("tag_") for k in (all_fields or {})),
        "Sender: who_is_this": "who_is_this" in (text_fields or {}),
        "Sender: importance": "sender_importance" in (all_fields or {}),
        "Sender: context": "sender_context" in (text_fields or {}),
        "Sender: worth_surfacing": "worth_surfacing" in (all_fields or {}),
    }

    all_present = True
    for label, found in checks.items():
        icon = "✓" if found else "✗"
        print(f"  {icon} {label}: {'field detected' if found else 'NOT FOUND'}")
        if not found:
            all_present = False

    print()
    if all_present:
        print("  All fields detected. Check values above to confirm")
        print("  Boox NeoReader preserved the filled data.")
    else:
        print("  Some fields missing. This may indicate NeoReader")
        print("  doesn't support this field type, or the form wasn't saved.")


if __name__ == "__main__":
    main()
