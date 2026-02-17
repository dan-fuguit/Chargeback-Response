"""
CHARGEBACK GENERATOR - FRAUD
chargeback_generator_fraud.py

For fraud/unauthorized transaction disputes with KYC, session evidence, and Shopify screenshots.
"""

import requests
import json
import os
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.lib.colors import HexColor
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable, Image
from reportlab.lib.enums import TA_CENTER

# Import footer
from pdf_footer import build_pdf_with_footer
from public_records import format_public_records_for_pdf, create_public_records_table_data

# Configuration
N8N_WEBHOOK = "https://dan-fugu.app.n8n.cloud/webhook/55614aa6-0d64-4390-ab2c-d595b6e0fda4"


def parse_merged_response(merged_response):
    llm_data = {}
    kyc_images = {'id_card': None, 'selfie': None, 'card': None}

    if isinstance(merged_response, dict):
        if 'output' in merged_response:
            output = merged_response['output']
            if isinstance(output, str):
                try:
                    llm_data = json.loads(output)
                except json.JSONDecodeError as e:
                    print(f"JSON parse error: {e}")
            else:
                llm_data = output

        if 'kyc_images' in merged_response:
            kyc_images = merged_response['kyc_images']

    return llm_data, kyc_images


def download_image(url, filename):
    try:
        print(f"Downloading: {url[:80]}...")
        response = requests.get(url, timeout=30)
        print(f"Response status: {response.status_code}")

        if response.status_code == 200:
            temp_path = os.path.join(os.environ.get('TEMP', '/tmp'), filename)
            with open(temp_path, 'wb') as f:
                f.write(response.content)
            print(f"Saved to: {temp_path}")
            return temp_path
        else:
            print(f"Download failed with status {response.status_code}")
    except Exception as e:
        print(f"Error downloading: {e}")
    return None


def create_proof_placeholder(placeholder_text):
    placeholder_data = [[f"[ {placeholder_text} ]"]]
    placeholder_table = Table(placeholder_data, colWidths=[6.5 * inch], rowHeights=[1.5 * inch])
    placeholder_table.setStyle(TableStyle([
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('FONTNAME', (0, 0), (-1, -1), 'Helvetica-Oblique'),
        ('FONTSIZE', (0, 0), (-1, -1), 10),
        ('TEXTCOLOR', (0, 0), (-1, -1), HexColor('#718096')),
        ('BACKGROUND', (0, 0), (-1, -1), HexColor('#f7fafc')),
        ('BOX', (0, 0), (-1, -1), 2, HexColor('#cbd5e0')),
    ]))
    return placeholder_table


def add_screenshot_to_story(story, screenshot_path, placeholder_text, caption=None):
    """Helper to add screenshot or placeholder to story"""
    caption_style = ParagraphStyle('caption', fontSize=8, alignment=TA_CENTER, textColor=HexColor('#4a5568'))

    if screenshot_path and os.path.exists(screenshot_path):
        try:
            img = Image(screenshot_path)
            img_width, img_height = img.wrap(0, 0)
            max_width = 6.5 * inch
            max_height = 3.5 * inch
            scale = min(max_width / img_width, max_height / img_height, 1)
            img.drawWidth = img_width * scale
            img.drawHeight = img_height * scale
            story.append(img)

            if caption:
                story.append(Spacer(1, 4))
                story.append(Paragraph(f"<i>{caption}</i>", caption_style))
            return True
        except Exception as e:
            print(f"Error loading screenshot {screenshot_path}: {e}")

    story.append(create_proof_placeholder(placeholder_text))
    return False


def create_kyc_section(kyc_images):
    elements = []

    print(f"Creating KYC section with images: {kyc_images}")

    id_card_path = download_image(kyc_images['id_card'], 'kyc_id.png') if kyc_images.get('id_card') else None
    selfie_path = download_image(kyc_images['selfie'], 'kyc_selfie.png') if kyc_images.get('selfie') else None
    card_path = download_image(kyc_images['card'], 'kyc_card.png') if kyc_images.get('card') else None

    print(f"Downloaded paths - ID: {id_card_path}, Selfie: {selfie_path}, Card: {card_path}")

    available_images = []
    if id_card_path:
        available_images.append((id_card_path, "Government-Issued ID"))
    if selfie_path:
        available_images.append((selfie_path, "Live Selfie Verification"))
    if card_path:
        available_images.append((card_path, "Payment Card Verification"))

    if not available_images:
        return elements

    num_images = len(available_images)
    col_width = 6.5 * inch / num_images
    img_max_width = col_width - 0.2 * inch
    img_max_height = 1.8 * inch

    image_cells = []
    caption_cells = []
    caption_style = ParagraphStyle('caption', fontSize=8, alignment=TA_CENTER, textColor=HexColor('#4a5568'))

    for img_path, caption in available_images:
        try:
            img = Image(img_path)
            iw, ih = img.wrap(0, 0)
            scale = min(img_max_width / iw, img_max_height / ih, 1)
            img.drawWidth = iw * scale
            img.drawHeight = ih * scale
            image_cells.append(img)
        except Exception as e:
            print(f"Error loading image: {e}")
            placeholder_style = ParagraphStyle('ph', alignment=TA_CENTER, fontSize=8, textColor=HexColor('#718096'))
            image_cells.append(Paragraph(f"[{caption}]", placeholder_style))

        caption_cells.append(Paragraph(f"<i>{caption}</i>", caption_style))

    images_table = Table([image_cells], colWidths=[col_width] * num_images, rowHeights=[2 * inch])
    images_table.setStyle(TableStyle([
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('BACKGROUND', (0, 0), (-1, -1), HexColor('#f7fafc')),
        ('BOX', (0, 0), (-1, -1), 1, HexColor('#cbd5e0')),
        ('INNERGRID', (0, 0), (-1, -1), 0.5, HexColor('#e2e8f0')),
        ('LEFTPADDING', (0, 0), (-1, -1), 5),
        ('RIGHTPADDING', (0, 0), (-1, -1), 5),
    ]))
    elements.append(images_table)

    captions_table = Table([caption_cells], colWidths=[col_width] * num_images)
    captions_table.setStyle(TableStyle([
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
    ]))
    elements.append(captions_table)

    return elements


def has_kyc_images(kyc_images):
    return any([kyc_images.get('id_card'), kyc_images.get('selfie'), kyc_images.get('card')])


def build_interaction_history_text(session_evidence):
    """Build the CUSTOMER INTERACTION HISTORY text from session evidence"""
    if not session_evidence:
        return None

    parts = []

    # Session activity
    session_data = session_evidence.get('session_evidence', {})
    if session_data and session_data.get('summary'):
        parts.append(session_data['summary'])

    # Location/IP info
    location_data = session_evidence.get('location_evidence', {})
    if location_data and location_data.get('summary'):
        parts.append(location_data['summary'])

    # Device info
    device_data = session_evidence.get('device_evidence', {})
    if device_data and device_data.get('summary'):
        parts.append(device_data['summary'])

    if parts:
        return '\n\n'.join(parts)

    return None


def generate_pdf(data, kyc_images, output_path, session_evidence=None, tenant_name=None, screenshots=None,
                 public_records_data=None, location_map_data=None):
    """
    Generate fraud chargeback PDF.

    Args:
        data: LLM response data
        kyc_images: Dict with KYC image URLs
        output_path: Where to save PDF
        session_evidence: Session evidence from database
        tenant_name: Tenant/store name
        screenshots: Dict with 'order_screenshot', 'tracking_screenshot', 'identity_screenshot', 'location_screenshot' paths
        public_records_data: Dict with public records from Redis (when LLM indicates match)
        location_map_data: Dict with location map screenshot and analysis
    """
    screenshots = screenshots or {}

    doc = SimpleDocTemplate(
        output_path,
        pagesize=letter,
        rightMargin=0.75 * inch,
        leftMargin=0.75 * inch,
        topMargin=0.75 * inch,
        bottomMargin=0.75 * inch
    )

    styles = getSampleStyleSheet()

    title_style = ParagraphStyle(
        'CustomTitle', parent=styles['Title'],
        fontSize=18, textColor=HexColor('#1a365d'),
        spaceAfter=6, alignment=TA_CENTER
    )

    subtitle_style = ParagraphStyle(
        'Subtitle', parent=styles['Normal'],
        fontSize=10, textColor=HexColor('#4a5568'),
        alignment=TA_CENTER, spaceAfter=20
    )

    section_header_style = ParagraphStyle(
        'SectionHeader', parent=styles['Heading2'],
        fontSize=11, textColor=HexColor('#2c5282'),
        spaceBefore=14, spaceAfter=6,
    )

    body_style = ParagraphStyle(
        'CustomBody', parent=styles['Normal'],
        fontSize=10, leading=13, textColor=HexColor('#2d3748'),
        spaceAfter=4,
    )

    conclusion_style = ParagraphStyle(
        'Conclusion', parent=body_style,
        fontSize=10, textColor=HexColor('#1a365d'),
        fontName='Helvetica-Bold',
    )

    caption_style = ParagraphStyle(
        'Caption', parent=styles['Normal'],
        fontSize=8, alignment=TA_CENTER, textColor=HexColor('#4a5568')
    )

    link_style = ParagraphStyle(
        'Link', parent=styles['Normal'],
        fontSize=9, textColor=HexColor('#2563eb')
    )

    story = []

    # Title
    has_kyc = has_kyc_images(kyc_images)
    subtitle_text = "Formal Evidence Submission with KYC Verification" if has_kyc else "Formal Evidence Submission"

    story.append(Paragraph("CHARGEBACK DISPUTE RESPONSE", title_style))
    story.append(Paragraph(subtitle_text, subtitle_style))
    story.append(HRFlowable(width="100%", thickness=2, color=HexColor('#2c5282'), spaceAfter=15))

    # Transaction Details
    amount = data.get('amount', 0)
    amount_str = f"${amount:.2f}" if isinstance(amount, (int, float)) else f"${amount}"

    chargeback_reason = data.get('chargeback_reason') or 'Not Specified'
    if isinstance(chargeback_reason, str):
        chargeback_reason = chargeback_reason.replace('_', ' ').title()

    reference = data.get('reference') or data.get('transaction_id', '')

    transaction_data = [
        ["Reference:", reference],
        ["Amount:", f"{amount_str} {data.get('currency', 'USD')}"],
        ["Transaction Date:", data.get('transaction_date', '')],
        ["Dispute Reason:", chargeback_reason],
    ]

    table = Table(transaction_data, colWidths=[1.4 * inch, 5.1 * inch])
    table.setStyle(TableStyle([
        ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
        ('FONTNAME', (1, 0), (1, -1), 'Helvetica'),
        ('FONTSIZE', (0, 0), (-1, -1), 9),
        ('TEXTCOLOR', (0, 0), (0, -1), HexColor('#4a5568')),
        ('TEXTCOLOR', (1, 0), (1, -1), HexColor('#1a202c')),
        ('ALIGN', (0, 0), (0, -1), 'RIGHT'),
        ('ALIGN', (1, 0), (1, -1), 'LEFT'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ('TOPPADDING', (0, 0), (-1, -1), 6),
        ('BACKGROUND', (0, 0), (-1, -1), HexColor('#f7fafc')),
        ('BOX', (0, 0), (-1, -1), 1, HexColor('#e2e8f0')),
        ('LINEBELOW', (0, 0), (-1, -2), 0.5, HexColor('#e2e8f0')),
    ]))
    story.append(table)
    story.append(Spacer(1, 15))

    # Opening Statement
    if data.get('opening_statement'):
        story.append(Paragraph("<b>SUMMARY:</b> " + data['opening_statement'], body_style))
        story.append(Spacer(1, 10))

    section_number = 1

    # Build interaction history text from session evidence if available
    interaction_history_text = build_interaction_history_text(session_evidence)

    # Evidence sections in order
    evidence_sections = [
        ("ORDER DETAILS", "order_details", True),
        ("PAYMENT VERIFICATION", "payment_proof", True),  # Card details + AVS if available
        ("IDENTITY VERIFICATION", "identity_proof", True),
        ("KYC VERIFICATION", "kyc_proof", False),
        ("PUBLIC RECORDS VERIFICATION", "public_records_proof", False),
        ("SHIPPING VERIFICATION", "shipping_proof", True),
        ("IP LOCATION VERIFICATION", "location_proof", False),
        ("CUSTOMER INTERACTION HISTORY", "interaction_proof", True),
    ]

    for header, key, always_show in evidence_sections:
        proof_data = data.get(key)

        # Special handling for ORDER DETAILS - add Shopify order screenshot
        if key == "order_details":
            story.append(Paragraph(f"<b>{section_number}. {header}</b>", section_header_style))

            order_text = f"Order {reference} placed on {data.get('transaction_date', '')} totaling {amount_str} {data.get('currency', 'USD')}."
            if proof_data:
                if isinstance(proof_data, dict):
                    order_text = proof_data.get('text', order_text)
                else:
                    order_text = proof_data
            story.append(Paragraph(order_text, body_style))
            story.append(Spacer(1, 6))

            # Add Shopify order screenshot
            add_screenshot_to_story(
                story,
                screenshots.get('order_screenshot'),
                "INSERT: Order Details Screenshot",
                caption="Shopify Order Details"
            )
            story.append(Spacer(1, 10))
            section_number += 1
            continue

        # Special handling for PAYMENT VERIFICATION - show card details + AVS if available
        if key == "payment_proof":
            story.append(Paragraph(f"<b>{section_number}. {header}</b>", section_header_style))
            story.append(Paragraph("The following payment details were captured and verified during the transaction:",
                                   body_style))
            story.append(Spacer(1, 6))

            # Always show card details image first
            add_screenshot_to_story(
                story,
                screenshots.get('card_details_screenshot'),
                "INSERT: Card Details Screenshot",
                caption="Payment Gateway Card Details"
            )

            # Add AVS screenshot if available (for fraud cases with AVS Y match)
            if screenshots.get('avs_screenshot'):
                story.append(Spacer(1, 10))
                if proof_data:
                    payment_text = None
                    if isinstance(proof_data, dict):
                        payment_text = proof_data.get('text')
                    else:
                        payment_text = proof_data
                    if payment_text:
                        story.append(Paragraph(payment_text, body_style))
                        story.append(Spacer(1, 6))

                add_screenshot_to_story(
                    story,
                    screenshots.get('avs_screenshot'),
                    "INSERT: AVS Verification Screenshot",
                    caption="AVS & Payment Verification Details"
                )

            story.append(Spacer(1, 10))
            section_number += 1
            continue

        # Special handling for IDENTITY VERIFICATION - add Fugu screenshot
        if key == "identity_proof":
            story.append(Paragraph(f"<b>{section_number}. {header}</b>", section_header_style))

            identity_text = "The following payment information was collected and verified during the transaction:"
            if proof_data:
                if isinstance(proof_data, dict):
                    identity_text = proof_data.get('text', identity_text)
                else:
                    identity_text = proof_data
            story.append(Paragraph(identity_text, body_style))
            story.append(Spacer(1, 6))

            # Add Fugu identity screenshot
            add_screenshot_to_story(
                story,
                screenshots.get('identity_screenshot'),
                "INSERT: Identity Verification Screenshot",
                caption="Payment Identity Information"
            )
            story.append(Spacer(1, 10))
            section_number += 1
            continue

        # Special handling for KYC - add images if available
        if key == "kyc_proof" and has_kyc:
            story.append(Paragraph(f"<b>{section_number}. {header}</b>", section_header_style))

            kyc_text = None
            if proof_data:
                if isinstance(proof_data, dict):
                    kyc_text = proof_data.get('text')
                else:
                    kyc_text = proof_data

            if not kyc_text:
                kyc_text = "Customer completed comprehensive identity verification including government-issued ID validation and live facial recognition."

            story.append(Paragraph(kyc_text, body_style))
            story.append(Spacer(1, 8))

            kyc_elements = create_kyc_section(kyc_images)
            for elem in kyc_elements:
                story.append(elem)

            story.append(Spacer(1, 10))
            section_number += 1
            continue

        # Skip kyc_proof if no images and no text
        if key == "kyc_proof" and not has_kyc and not proof_data:
            continue

        # Special handling for PUBLIC RECORDS VERIFICATION - show Redis data if available
        if key == "public_records_proof" and proof_data:
            story.append(Paragraph(f"<b>{section_number}. {header}</b>", section_header_style))

            # Use LLM text first
            pr_text = None
            if isinstance(proof_data, dict):
                pr_text = proof_data.get('text')
            else:
                pr_text = proof_data

            if pr_text:
                story.append(Paragraph(pr_text, body_style))
                story.append(Spacer(1, 6))

            # Add table with public records data from Redis if available
            if public_records_data:
                # Add explanation about the phone number
                phone_number = public_records_data.get('_phone_number', '')
                if phone_number:
                    story.append(Paragraph(
                        f"The following public records are associated with the phone number <b>{phone_number}</b>, "
                        "which was provided by the customer when placing this order:",
                        body_style
                    ))
                    story.append(Spacer(1, 6))

                table_data = create_public_records_table_data(public_records_data)

                # Add phone number at the top of the table
                if phone_number:
                    table_data.insert(0, ["Phone Number:", phone_number])

                if table_data:
                    pr_table = Table(table_data, colWidths=[1.8 * inch, 4.7 * inch])
                    pr_table.setStyle(TableStyle([
                        ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
                        ('FONTNAME', (1, 0), (1, -1), 'Helvetica'),
                        ('FONTSIZE', (0, 0), (-1, -1), 9),
                        ('TEXTCOLOR', (0, 0), (0, -1), HexColor('#4a5568')),
                        ('TEXTCOLOR', (1, 0), (1, -1), HexColor('#1a202c')),
                        ('ALIGN', (0, 0), (0, -1), 'RIGHT'),
                        ('ALIGN', (1, 0), (1, -1), 'LEFT'),
                        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
                        ('TOPPADDING', (0, 0), (-1, -1), 6),
                        ('BACKGROUND', (0, 0), (-1, -1), HexColor('#f0fff4')),  # Light green background
                        ('BOX', (0, 0), (-1, -1), 1, HexColor('#9ae6b4')),
                        ('LINEBELOW', (0, 0), (-1, -2), 0.5, HexColor('#c6f6d5')),
                    ]))
                    story.append(pr_table)

            story.append(Spacer(1, 10))
            section_number += 1
            continue

        # Special handling for SHIPPING VERIFICATION - use tracking screenshot
        if key == "shipping_proof":
            story.append(Paragraph(f"<b>{section_number}. {header}</b>", section_header_style))

            shipping_text = "Please find below the Delivery Confirmation Receipt confirming successful delivery of the order:"
            if proof_data:
                if isinstance(proof_data, dict):
                    shipping_text = proof_data.get('text', shipping_text)
                else:
                    shipping_text = proof_data
            story.append(Paragraph(shipping_text, body_style))
            story.append(Spacer(1, 6))

            # Add tracking screenshot from screenshots dict
            add_screenshot_to_story(
                story,
                screenshots.get('tracking_screenshot'),
                "INSERT: Delivery Confirmation Screenshot",
                caption="Carrier Delivery Confirmation"
            )

            # Add tracking URL link if available
            if screenshots.get('tracking_url'):
                story.append(Spacer(1, 6))
                story.append(Paragraph(
                    f"Tracking link: <link href='{screenshots['tracking_url']}'><u>{screenshots['tracking_url']}</u></link>",
                    link_style))

            story.append(Spacer(1, 10))
            section_number += 1
            continue

        # Special handling for IP LOCATION VERIFICATION - use map
        if key == "location_proof" and proof_data:
            story.append(Paragraph(f"<b>{section_number}. {header}</b>", section_header_style))

            # Use location map analysis text if available, otherwise LLM text
            location_text = None
            if location_map_data and location_map_data.get('analysis', {}).get('summary_text'):
                location_text = location_map_data['analysis']['summary_text']
            elif isinstance(proof_data, dict):
                location_text = proof_data.get('text')
            else:
                location_text = proof_data

            if location_text:
                story.append(Paragraph(location_text, body_style))
                story.append(Spacer(1, 6))

            # Add location map screenshot
            add_screenshot_to_story(
                story,
                screenshots.get('location_screenshot'),
                "INSERT: IP Location Map",
                caption="IP Location vs Billing/Shipping Address"
            )
            story.append(Spacer(1, 10))
            section_number += 1
            continue

        # Special handling for CUSTOMER INTERACTION HISTORY - use session evidence
        if key == "interaction_proof":
            story.append(Paragraph(f"<b>{section_number}. {header}</b>", section_header_style))

            # Use session evidence if available, otherwise fall back to LLM data or default
            if interaction_history_text:
                # Replace newlines with <br/> for PDF
                formatted_text = interaction_history_text.replace('\n', '<br/>')
                story.append(Paragraph(formatted_text, body_style))
            elif proof_data:
                if isinstance(proof_data, dict):
                    text = proof_data.get('text', 'Customer interaction and communication history.')
                else:
                    text = proof_data
                story.append(Paragraph(text, body_style))
            else:
                story.append(Paragraph("Customer interaction and communication history.", body_style))

            story.append(Spacer(1, 6))
            story.append(create_proof_placeholder("INSERT: Customer Interaction Screenshot"))
            story.append(Spacer(1, 10))
            section_number += 1
            continue

        # Always show certain sections even without LLM data
        if always_show and not proof_data:
            story.append(Paragraph(f"<b>{section_number}. {header}</b>", section_header_style))
            story.append(Paragraph("Evidence documentation.", body_style))
            story.append(Spacer(1, 6))
            story.append(create_proof_placeholder(f"INSERT: {header} Screenshot"))
            story.append(Spacer(1, 10))
            section_number += 1
            continue

        # Regular sections
        if proof_data:
            if isinstance(proof_data, dict):
                text = proof_data.get('text')
                placeholder = proof_data.get('proof_placeholder', f'{header} Screenshot')
            else:
                text = proof_data
                placeholder = f'{header} Screenshot'

            if text:
                story.append(Paragraph(f"<b>{section_number}. {header}</b>", section_header_style))
                story.append(Paragraph(text, body_style))
                story.append(Spacer(1, 6))
                story.append(create_proof_placeholder(f"INSERT: {placeholder}"))
                story.append(Spacer(1, 10))
                section_number += 1

    # Closing Statement
    story.append(Spacer(1, 10))
    story.append(HRFlowable(width="100%", thickness=1, color=HexColor('#e2e8f0'), spaceAfter=10))

    if data.get('closing_statement'):
        story.append(Paragraph("<b>CONCLUSION</b>", section_header_style))
        story.append(Paragraph(data['closing_statement'], conclusion_style))

    build_pdf_with_footer(doc, story)
    print(f"PDF created: {output_path}")
    return output_path


def process_chargeback(paymentid, reason="unrecognized_transaction"):
    """Standalone processing - used when running this file directly"""
    from shopify_order_screenshot import screenshot_shopify_order
    from shopify_tracking import get_shipping_proof

    payload = {
        "paymentid": paymentid,
        "reason": reason
    }

    print(f"Sending payload: {payload}")

    r = requests.post(N8N_WEBHOOK, json=payload, timeout=120)

    print(f"Response status: {r.status_code}")
    print(f"Response text: {r.text[:500] if r.text else 'EMPTY'}")

    if not r.text:
        print("ERROR: Empty response from webhook")
        return None

    try:
        merged_response = r.json()
    except Exception as e:
        print(f"JSON parse error: {e}")
        print(f"Raw response: {r.text}")
        return None

    print(f"Response type: {type(merged_response)}")

    data, kyc_images = parse_merged_response(merged_response)

    print(f"Parsed data type: {type(data)}")
    print(f"KYC images: {kyc_images}")

    ref = data.get('reference') or paymentid
    tenant = data.get('tenant') or data.get('tenant_name')

    # Get screenshots
    screenshots = {}
    if tenant and ref:
        print(f"Capturing screenshots for tenant={tenant}, reference={ref}")

        # Order screenshot
        order_path = screenshot_shopify_order(tenant, ref, "/tmp")
        if order_path:
            screenshots['order_screenshot'] = order_path

        # Tracking screenshot
        tracking_info = get_shipping_proof(tenant_name=tenant, reference=ref, output_dir="/tmp")
        if tracking_info and tracking_info.get('screenshot_path'):
            screenshots['tracking_screenshot'] = tracking_info['screenshot_path']

    output_path = f"chargeback_dispute_{ref}.pdf"
    generate_pdf(data, kyc_images, output_path, screenshots=screenshots)

    return output_path


if __name__ == "__main__":
    import sys

    paymentid = sys.argv[1] if len(sys.argv) > 1 else None
    reason = sys.argv[2] if len(sys.argv) > 2 else "unrecognized_transaction"

    if not paymentid:
        print("Usage: python chargeback_generator_fraud.py <paymentid> [reason]")
        sys.exit(1)

    process_chargeback(paymentid, reason)