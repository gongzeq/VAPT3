#!/usr/bin/env python3
"""Render a local HTML slide deck to a PDF.

Default:
    python3 convert_report_pdf.py

Custom files:
    python3 convert_report_pdf.py input.html output.pdf
"""

from __future__ import annotations

import argparse
from io import BytesIO
from pathlib import Path

from PIL import Image
from playwright.sync_api import sync_playwright


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Render an interactive HTML slide deck to a PDF."
    )
    parser.add_argument("html", nargs="?", default="汇报.html", help="Input HTML file")
    parser.add_argument("pdf", nargs="?", default="汇报.pdf", help="Output PDF file")
    parser.add_argument(
        "--width",
        type=int,
        default=1600,
        help="Viewport width in pixels; default: 1600",
    )
    parser.add_argument(
        "--height",
        type=int,
        default=900,
        help="Viewport height in pixels; default: 900",
    )
    parser.add_argument(
        "--scale",
        type=float,
        default=2.0,
        help="Device scale factor for sharper output; default: 2",
    )
    parser.add_argument(
        "--dpi",
        type=float,
        default=200.0,
        help="PDF image resolution; default: 200",
    )
    parser.add_argument(
        "--wait",
        type=int,
        default=950,
        help="Milliseconds to wait after switching slides; default: 950",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    html_path = Path(args.html).expanduser().resolve()
    pdf_path = Path(args.pdf).expanduser().resolve()

    if not html_path.exists():
        raise SystemExit(f"Input HTML does not exist: {html_path}")

    images: list[Image.Image] = []

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(
            viewport={"width": args.width, "height": args.height},
            device_scale_factor=args.scale,
        )
        page.goto(html_path.as_uri(), wait_until="networkidle")
        page.evaluate("document.fonts && document.fonts.ready")
        page.add_style_tag(
            content="""
            .hint, .dots, .progress { display: none !important; }
            .bg-scan { display: none !important; }
            .slide .reveal {
              opacity: 1 !important;
              transform: none !important;
              animation: none !important;
            }
            """
        )

        slide_count = page.eval_on_selector_all(".slide", "slides => slides.length")
        if slide_count == 0:
            raise SystemExit("No .slide elements found in the HTML file.")

        for index in range(slide_count):
            page.eval_on_selector_all(
                ".slide",
                """
                (slides, index) => {
                  slides.forEach((slide, i) => {
                    const active = i === index;
                    slide.classList.toggle('active', active);
                    slide.classList.toggle('exit-up', i < index);
                    slide.style.opacity = active ? '1' : '0';
                    slide.style.visibility = active ? 'visible' : 'hidden';
                    slide.style.transform = active ? 'none' : 'translateY(28px) scale(.985)';
                  });
                }
                """,
                index,
            )

            page.wait_for_timeout(args.wait)
            screenshot = page.screenshot(full_page=False, type="png")
            images.append(Image.open(BytesIO(screenshot)).convert("RGB"))

        browser.close()

    pdf_path.parent.mkdir(parents=True, exist_ok=True)
    images[0].save(
        pdf_path,
        "PDF",
        resolution=args.dpi,
        save_all=True,
        append_images=images[1:],
        quality=95,
    )
    print(f"Wrote {pdf_path} with {len(images)} pages")


if __name__ == "__main__":
    main()
