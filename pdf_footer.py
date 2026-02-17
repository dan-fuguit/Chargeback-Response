"""
Shared PDF footer with FUGU branding
Used by all chargeback generators
"""

import os
from reportlab.lib.colors import HexColor
from reportlab.lib.units import inch
from reportlab.platypus import Image, Paragraph, Table, TableStyle
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.enums import TA_CENTER

# FUGU brand color
FUGU_COLOR = HexColor('#2873C2')

# Logo path
LOGO_PATH = "fugu_logo.png"


class FuguFooter:
    """Footer canvas handler for adding FUGU branding to each page"""

    def __init__(self, canvas, doc):
        self.canvas = canvas
        self.doc = doc

    @staticmethod
    def add_footer(canvas, doc):
        """Add 'Powered by FUGU' footer to each page"""
        canvas.saveState()

        page_width = doc.pagesize[0]
        footer_y = 0.4 * inch

        # Check if logo exists
        logo_path = LOGO_PATH
        if not os.path.exists(logo_path):
            # Try alternate paths
            for path in ['fugu_logo.png', './fugu_logo.png', '../fugu_logo.png']:
                if os.path.exists(path):
                    logo_path = path
                    break

        if os.path.exists(logo_path):
            # Draw logo + text
            try:
                # Draw "Powered by" text
                canvas.setFillColor(FUGU_COLOR)
                canvas.setFont("Helvetica", 8)

                # Calculate positions for centered layout
                text = "Powered by"
                text_width = canvas.stringWidth(text, "Helvetica", 8)

                # Load and measure logo
                from reportlab.lib.utils import ImageReader
                img = ImageReader(logo_path)
                img_width, img_height = img.getSize()

                # Scale logo to ~20px height
                logo_height = 20
                logo_width = (img_width / img_height) * logo_height

                # Total width: text + space + logo
                total_width = text_width + 5 + logo_width
                start_x = (page_width - total_width) / 2

                # Draw text
                canvas.drawString(start_x, footer_y, text)

                # Draw logo
                canvas.drawImage(
                    logo_path,
                    start_x + text_width + 5,
                    footer_y - 5,
                    width=logo_width,
                    height=logo_height,
                    preserveAspectRatio=True,
                    mask='auto'
                )

            except Exception as e:
                print(f"Error drawing logo: {e}")
                # Fallback to text only
                canvas.setFillColor(FUGU_COLOR)
                canvas.setFont("Helvetica-Bold", 9)
                canvas.drawCentredString(page_width / 2, footer_y, "Powered by FUGU")
        else:
            # No logo - text only
            canvas.setFillColor(FUGU_COLOR)
            canvas.setFont("Helvetica-Bold", 9)
            canvas.drawCentredString(page_width / 2, footer_y, "Powered by FUGU")

        canvas.restoreState()


def build_pdf_with_footer(doc, story):
    """Build PDF with FUGU footer on each page"""
    doc.build(
        story,
        onFirstPage=FuguFooter.add_footer,
        onLaterPages=FuguFooter.add_footer
    )