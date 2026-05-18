"""
test_reports.py

Quick test to verify report generation and filename labeling
before committing. Tests 2 artists with different expected decisions.

Run with:
    python test_reports.py
"""

import sys
import os
sys.path.insert(0, '.')

from dotenv import load_dotenv
load_dotenv()

import logging
logging.basicConfig(level=logging.WARNING, format="%(asctime)s %(levelname)s %(message)s")

from agents.research_graph import run_research

print("=" * 60)
print("REPORT GENERATION TEST")
print("=" * 60)

# Test 1 — Fisher (electronic, high score → expect SIGN)
print("\nTest 1: Fisher (electronic, triage=85)")
print("-" * 40)
try:
    result1 = run_research(
        artist_name="Fisher",
        genre="electronic",
        triage_score=85,
    )
    print(f"  Decision label in filename: {result1.get('decision_label', 'unknown')}")
    print(f"  Report path: {result1.get('report_path', 'none')}")
    print(f"  PDF path:    {result1.get('pdf_path', 'none')}")
    print(f"  Errors:      {result1.get('errors', [])}")

    # Check file exists
    md_path = result1.get("report_path", "")
    if md_path and os.path.exists(md_path):
        print(f"  ✓ Markdown file exists ({os.path.getsize(md_path):,} bytes)")
        # Check filename has correct label
        if "SIGN" in md_path:
            print("  ✓ Filename correctly labelled SIGN")
        elif "WATCH" in md_path:
            print("  ⚠ Filename labelled WATCH (score was 85 — check report content)")
        else:
            print("  ✗ Unexpected filename label")
    else:
        print(f"  ✗ Markdown file not found: {md_path}")

    pdf_path = result1.get("pdf_path", "")
    if pdf_path and os.path.exists(pdf_path):
        print(f"  ✓ PDF file exists ({os.path.getsize(pdf_path):,} bytes)")
    else:
        print("  ⚠ PDF not generated (markdown only)")

except Exception as e:
    print(f"  ✗ FAILED: {e}")

# Test 2 — Rema (afrobeats, lower score → expect WATCH)
print("\nTest 2: Rema (afrobeats, triage=67)")
print("-" * 40)
try:
    result2 = run_research(
        artist_name="Rema",
        genre="afrobeats",
        triage_score=67,
    )
    print(f"  Decision label in filename: {result2.get('decision_label', 'unknown')}")
    print(f"  Report path: {result2.get('report_path', 'none')}")
    print(f"  PDF path:    {result2.get('pdf_path', 'none')}")
    print(f"  Errors:      {result2.get('errors', [])}")

    md_path = result2.get("report_path", "")
    if md_path and os.path.exists(md_path):
        print(f"  ✓ Markdown file exists ({os.path.getsize(md_path):,} bytes)")
        if "WATCH" in md_path:
            print("  ✓ Filename correctly labelled WATCH")
        elif "SIGN" in md_path:
            print("  ⚠ Filename labelled SIGN (score was 67 — check report content)")
        else:
            print("  ✗ Unexpected filename label")
    else:
        print(f"  ✗ Markdown file not found: {md_path}")

    pdf_path = result2.get("pdf_path", "")
    if pdf_path and os.path.exists(pdf_path):
        print(f"  ✓ PDF file exists ({os.path.getsize(pdf_path):,} bytes)")
    else:
        print("  ⚠ PDF not generated (markdown only)")

except Exception as e:
    print(f"  ✗ FAILED: {e}")

print("\n" + "=" * 60)
print("Check reports/ folder for generated files")
print("=" * 60)

# List all files in reports/
print("\nFiles in reports/:")
if os.path.exists("reports"):
    for f in sorted(os.listdir("reports")):
        size = os.path.getsize(os.path.join("reports", f))
        print(f"  {f} ({size:,} bytes)")
else:
    print("  reports/ folder not found")
