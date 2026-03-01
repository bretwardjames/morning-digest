#!/usr/bin/env python
"""Generate a test PDF with real AcroForm fields for Boox NeoReader validation.

Run this, upload the PDF to your Boox via Google Drive, and verify:
1. Checkboxes are tappable
2. Radio buttons are selectable (only one per group)
3. Text fields accept input via on-screen keyboard
4. Filled values survive a Drive sync round-trip
5. pypdf can read back the filled values

Usage:
    python tests/generate_test_form.py

Output:
    tests/output/boox_form_test.pdf
"""

from pathlib import Path

from reportlab.lib.pagesizes import letter
from reportlab.lib.colors import black, HexColor
from reportlab.pdfgen.canvas import Canvas

OUTPUT_DIR = Path(__file__).parent / "output"
OUTPUT_FILE = OUTPUT_DIR / "boox_form_test.pdf"

# Layout constants
PAGE_W, PAGE_H = letter
LEFT = 72
RIGHT = PAGE_W - 72
CONTENT_W = RIGHT - LEFT


def main():
    OUTPUT_DIR.mkdir(exist_ok=True)
    c = Canvas(str(OUTPUT_FILE), pagesize=letter)

    # ── Page 1: Article-style feedback form ──────────────────────────
    y = PAGE_H - 72

    # Title
    c.setFont("Helvetica-Bold", 20)
    c.drawString(LEFT, y, "Boox AcroForm Validation Test")
    y -= 30

    c.setFont("Helvetica", 12)
    c.drawString(LEFT, y, "Fill out this form on your Boox, sync back, and run the reader script.")
    y -= 40

    # ── Section 1: Checkbox ──────────────────────────────────────────
    c.setFont("Helvetica-Bold", 16)
    c.drawString(LEFT, y, "1. Checkbox")
    y -= 28

    c.setFont("Helvetica", 14)
    c.drawString(LEFT, y, "Did you read this article?")
    c.acroForm.checkbox(
        name="was_read",
        x=LEFT + 280,
        y=y - 4,
        size=20,
        checked=False,
        buttonStyle="check",
        borderWidth=2,
        borderColor=black,
        forceBorder=True,
    )
    y -= 40

    # ── Section 2: Radio buttons (rating) ────────────────────────────
    c.setFont("Helvetica-Bold", 16)
    c.drawString(LEFT, y, "2. Radio Buttons — Rating")
    y -= 28

    c.setFont("Helvetica", 14)
    c.drawString(LEFT, y, "How would you rate it?")
    y -= 30

    for i in range(1, 11):
        col = (i - 1) % 5
        row = (i - 1) // 5
        bx = LEFT + col * 90
        by = y - row * 36

        c.setFont("Helvetica", 13)
        c.drawString(bx + 24, by + 2, str(i))
        c.acroForm.radio(
            name="rating",
            value=str(i),
            x=bx,
            y=by - 2,
            size=20,
            selected=(i == 5),
            buttonStyle="circle",
            shape="circle",
            borderWidth=2,
            borderColor=black,
            forceBorder=True,
        )

    y -= 80

    # ── Section 3: Text field (single line) ──────────────────────────
    c.setFont("Helvetica-Bold", 16)
    c.drawString(LEFT, y, "3. Text Field — Single Line")
    y -= 28

    c.setFont("Helvetica", 14)
    c.drawString(LEFT, y, "What topic was this about?")
    y -= 28

    c.acroForm.textfield(
        name="topic",
        x=LEFT,
        y=y - 4,
        width=CONTENT_W,
        height=24,
        fontSize=14,
        borderWidth=1,
        borderColor=black,
        forceBorder=True,
    )
    y -= 44

    # ── Section 4: Text field (multiline) ────────────────────────────
    c.setFont("Helvetica-Bold", 16)
    c.drawString(LEFT, y, "4. Text Field — Multiline")
    y -= 28

    c.setFont("Helvetica", 14)
    c.drawString(LEFT, y, "What did you like about it?")
    y -= 28

    c.acroForm.textfield(
        name="liked",
        x=LEFT,
        y=y - 60,
        width=CONTENT_W,
        height=64,
        fontSize=14,
        borderWidth=1,
        borderColor=black,
        fieldFlags="multiline",
        forceBorder=True,
    )
    y -= 100

    # ── Section 5: Radio group (want more) ───────────────────────────
    c.setFont("Helvetica-Bold", 16)
    c.drawString(LEFT, y, "5. Radio Buttons — Preference")
    y -= 28

    c.setFont("Helvetica", 14)
    options = [
        ("more", "Yes, more of this"),
        ("less", "No, less of this"),
        ("neutral", "Neutral"),
    ]
    for value, label in options:
        c.drawString(LEFT + 28, y + 2, label)
        c.acroForm.radio(
            name="want_more",
            value=value,
            x=LEFT,
            y=y - 2,
            size=20,
            buttonStyle="circle",
            shape="circle",
            borderWidth=2,
            borderColor=black,
            forceBorder=True,
        )
        y -= 30

    y -= 10

    # ── Section 6: Multiple checkboxes (tags) ────────────────────────
    c.setFont("Helvetica-Bold", 16)
    c.drawString(LEFT, y, "6. Checkboxes — Topic Tags")
    y -= 28

    c.setFont("Helvetica", 14)
    tags = ["AI/tech", "Business", "Politics", "Health"]
    for i, tag in enumerate(tags):
        c.drawString(LEFT + 28, y + 2, tag)
        c.acroForm.checkbox(
            name=f"tag_{tag.lower().replace('/', '_')}",
            x=LEFT,
            y=y - 2,
            size=20,
            checked=False,
            buttonStyle="check",
            borderWidth=2,
            borderColor=black,
            forceBorder=True,
        )
        y -= 30

    # ── Page 2: Sender onboarding form ───────────────────────────────
    c.showPage()
    y = PAGE_H - 72

    c.setFont("Helvetica-Bold", 20)
    c.drawString(LEFT, y, "New Sender — Classification Form")
    y -= 30

    c.setFont("Helvetica", 12)
    c.drawString(LEFT, y, "Test: Jane Doe <jane@example.com>")
    y -= 40

    # Who is this
    c.setFont("Helvetica-Bold", 14)
    c.drawString(LEFT, y, "Who is this person / what is this sender?")
    y -= 28

    c.acroForm.textfield(
        name="who_is_this",
        x=LEFT,
        y=y - 40,
        width=CONTENT_W,
        height=48,
        fontSize=14,
        borderWidth=1,
        borderColor=black,
        fieldFlags="multiline",
        forceBorder=True,
    )
    y -= 80

    # Importance
    c.setFont("Helvetica-Bold", 14)
    c.drawString(LEFT, y, "How important are their emails generally?")
    y -= 28

    c.setFont("Helvetica", 14)
    importance_options = [
        ("always", "Always read"),
        ("sometimes", "Sometimes"),
        ("rarely", "Rarely"),
        ("never", "Never surface"),
    ]
    for value, label in importance_options:
        c.drawString(LEFT + 28, y + 2, label)
        c.acroForm.radio(
            name="sender_importance",
            value=value,
            x=LEFT,
            y=y - 2,
            size=20,
            buttonStyle="circle",
            shape="circle",
            borderWidth=2,
            borderColor=black,
            forceBorder=True,
        )
        y -= 30

    y -= 10

    # Context
    c.setFont("Helvetica-Bold", 14)
    c.drawString(LEFT, y, "Any specific context?")
    y -= 8
    c.setFont("Helvetica", 11)
    c.setFillColor(HexColor("#888888"))
    c.drawString(LEFT, y, '(e.g. "my business partner — anything about clients is urgent")')
    c.setFillColor(black)
    y -= 24

    c.acroForm.textfield(
        name="sender_context",
        x=LEFT,
        y=y - 40,
        width=CONTENT_W,
        height=48,
        fontSize=14,
        borderWidth=1,
        borderColor=black,
        fieldFlags="multiline",
        forceBorder=True,
    )
    y -= 80

    # Worth surfacing
    c.setFont("Helvetica-Bold", 14)
    c.drawString(LEFT, y, "Was this email worth surfacing?")
    y -= 28

    c.setFont("Helvetica", 14)
    for value, label in [("yes", "Yes"), ("no", "No")]:
        c.drawString(LEFT + 28, y + 2, label)
        c.acroForm.radio(
            name="worth_surfacing",
            value=value,
            x=LEFT,
            y=y - 2,
            size=20,
            buttonStyle="circle",
            shape="circle",
            borderWidth=2,
            borderColor=black,
            forceBorder=True,
        )
        y -= 30

    # Hidden metadata
    y -= 20
    c.setFont("Helvetica", 7)
    c.setFillColor(HexColor("#aaaaaa"))
    c.drawString(LEFT, y, "sender_email:jane@example.com | sender_name:Jane Doe | account:gmail_primary")

    c.save()
    print(f"Generated: {OUTPUT_FILE}")
    print(f"File size: {OUTPUT_FILE.stat().st_size / 1024:.1f} KB")
    print()
    print("Next steps:")
    print("  1. Upload to your Boox Digest inbox folder on Google Drive")
    print("  2. Open in NeoReader on the Boox Go 10.3")
    print("  3. Try tapping checkboxes, radio buttons, and text fields")
    print("  4. Save and sync back to Drive")
    print("  5. Run: python tests/read_test_form.py")


if __name__ == "__main__":
    main()
