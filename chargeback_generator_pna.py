import requests
import json
import os
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.lib.colors import HexColor
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable, Image
from reportlab.lib.enums import TA_CENTER, TA_LEFT

# Import return policies from separate file
from return_policies import get_return_policy

# Import footer
from pdf_footer import build_pdf_with_footer

# Configuration - Same endpoint
N8N_WEBHOOK = "https://dan-fugu.app.n8n.cloud/webhook-test/55614aa6-0d64-4390-ab2c-d595b6e0fda4"

# Return policy screenshots folder
RETURN_POLICIES_FOLDER = "return_policies"


def get_return_policy_image(tenant_name):
    """Get return policy screenshot path for tenant"""
    if not tenant_name:
        return None

    tenant_key = tenant_name.lower().strip()

    # Check for common image extensions
    for ext in ['.png', '.jpg', '.jpeg', '.gif', '.webp']:
        image_path = os.path.join(RETURN_POLICIES_FOLDER, f"{tenant_key}{ext}")
        if os.path.exists(image_path):
            return image_path

    return None


def parse_response(response):
    llm_data = {}

    if isinstance(response, dict):
        if 'output' in response:
            output = response['output']
            if isinstance(output, str):
                try:
                    llm_data = json.loads(output)
                except json.JSONDecodeError as e:
                    print(f"JSON parse error: {e}")
            else:
                llm_data = output
        else:
            llm_data = response

    return llm_data


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


def generate_pdf(data, output_path, tenant_name=None, screenshots=None):
    """
    Generate PNA chargeback PDF.

    Args:
        data: LLM response data
        output_path: Where to save PDF
        tenant_name: Tenant/store name
        screenshots: Dict with 'order_screenshot' and 'tracking_screenshot' paths
    """
    screenshots = screenshots or {}

    # Get tenant-specific return policy
    return_policy = get_return_policy(tenant_name)
    return_policy_image = get_return_policy_image(tenant_name)

    if return_policy_image:
        print(f"Found return policy image: {return_policy_image}")
    else:
        print(f"No return policy image found for tenant: {tenant_name}")

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
        fontSize=10, leading=14, textColor=HexColor('#2d3748'),
        spaceAfter=4,
    )

    link_style = ParagraphStyle(
        'LinkStyle', parent=body_style,
        fontSize=9, textColor=HexColor('#2b6cb0'),
        spaceAfter=8,
    )

    conclusion_style = ParagraphStyle(
        'Conclusion', parent=body_style,
        fontSize=10, textColor=HexColor('#1a365d'),
        fontName='Helvetica-Bold',
    )

    bullet_style = ParagraphStyle(
        'BulletStyle', parent=body_style,
        fontSize=10, leftIndent=10,
    )

    story = []

    # Title
    story.append(Paragraph("CHARGEBACK DISPUTE RESPONSE", title_style))
    story.append(Paragraph("Product Unacceptable / Quality Dispute", subtitle_style))
    story.append(HRFlowable(width="100%", thickness=2, color=HexColor('#2c5282'), spaceAfter=15))

    # Transaction Details
    amount = data.get('amount', 0)
    amount_str = f"${amount:.2f}" if isinstance(amount, (int, float)) else f"${amount}"

    chargeback_reason = data.get('chargeback_reason') or 'Product Unacceptable'
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
    story.append(Spacer(1, 20))

    # Opening Statement - "Dear Issuer" format
    if data.get('opening_statement'):
        # Split by newlines and render each part
        opening_text = data['opening_statement']
        for line in opening_text.split('\n'):
            if line.strip():
                if line.strip().startswith('∙'):
                    story.append(Paragraph(line.strip(), bullet_style))
                else:
                    story.append(Paragraph(line.strip(), body_style))
        story.append(Spacer(1, 15))
    else:
        # Default opening
        customer_name = data.get('customer_name', 'the customer')
        gender = data.get('customer_gender', 'they').lower()
        pronoun = 'she' if gender == 'female' else ('he' if gender == 'male' else 'they')

        story.append(Paragraph("Dear Issuer,", body_style))
        story.append(Spacer(1, 8))
        story.append(Paragraph(
            f"Please be informed that we wish to decline the chargeback with reason code {chargeback_reason}. "
            f"The order was successfully delivered to the client in good condition and {pronoun} never claimed "
            f"about the quality of the item or asked for a return, so the chargeback is invalid.",
            body_style
        ))
        story.append(Spacer(1, 10))
        story.append(Paragraph("∙ Order details", bullet_style))
        story.append(Paragraph("∙ Payment proof", bullet_style))
        story.append(Paragraph("∙ Shipping proof", bullet_style))
        story.append(Paragraph("∙ Merchant's Returns & Exchanges Policy", bullet_style))
        story.append(Spacer(1, 15))

    # Section 1: Order Details with Shopify Screenshot
    story.append(Paragraph("<b>1. Order details</b>", section_header_style))
    order_text = "Please find below the details of order which was created on the merchant's web-site:"
    if data.get('order_details'):
        if isinstance(data['order_details'], dict):
            order_text = data['order_details'].get('text', order_text)
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

    # Section 2: Card Details
    story.append(Paragraph("<b>2. Card Details</b>", section_header_style))
    story.append(Paragraph("The following card details were captured from the payment gateway:", body_style))
    story.append(Spacer(1, 6))
    add_screenshot_to_story(
        story,
        screenshots.get('card_details_screenshot'),
        "INSERT: Card Details Screenshot",
        caption="Payment Gateway Card Details"
    )
    story.append(Spacer(1, 10))

    # Section 3: Shipping Proof with Tracking Screenshot
    story.append(Paragraph("<b>3. Shipping proof</b>", section_header_style))
    shipping_text = "Please find below the Delivery Confirmation Receipt confirming successful delivery of the order:"
    if data.get('shipping_proof'):
        if isinstance(data['shipping_proof'], dict):
            shipping_text = data['shipping_proof'].get('text', shipping_text)
    story.append(Paragraph(shipping_text, body_style))
    story.append(Spacer(1, 6))

    # Add tracking screenshot
    add_screenshot_to_story(
        story,
        screenshots.get('tracking_screenshot'),
        "INSERT: Delivery Confirmation Screenshot",
        caption="Carrier Delivery Confirmation"
    )
    story.append(Spacer(1, 10))

    # Section 4: Return/Exchange Policy (FROM LOCAL TENANT CONFIG)
    story.append(Paragraph("<b>4. Merchant's Return/Exchange Policy</b>", section_header_style))
    story.append(Paragraph(return_policy["text"], body_style))

    # Add policy URL
    if return_policy.get("url"):
        story.append(Spacer(1, 6))
        story.append(Paragraph("Merchant's Returns & Exchanges Policy can be found by the below link:", body_style))
        story.append(Paragraph(f"<u>{return_policy['url']}</u>", link_style))

    # Add policy screenshot or extract
    story.append(Spacer(1, 8))
    story.append(Paragraph("Here is an extract from merchant's refund policy:", body_style))
    story.append(Spacer(1, 6))

    # Insert actual image if available, otherwise placeholder
    if return_policy_image:
        try:
            img = Image(return_policy_image)
            # Scale to fit page width while maintaining aspect ratio
            img_width, img_height = img.wrap(0, 0)
            max_width = 6.5 * inch
            max_height = 4 * inch
            scale = min(max_width / img_width, max_height / img_height, 1)
            img.drawWidth = img_width * scale
            img.drawHeight = img_height * scale
            story.append(img)
        except Exception as e:
            print(f"Error loading return policy image: {e}")
            story.append(create_proof_placeholder("INSERT: Return Policy Screenshot"))
    else:
        story.append(create_proof_placeholder("INSERT: Return Policy Screenshot"))

    # Summary / Closing Statement
    story.append(Spacer(1, 15))
    story.append(HRFlowable(width="100%", thickness=1, color=HexColor('#e2e8f0'), spaceAfter=10))
    story.append(Paragraph("<b>Summary</b>", section_header_style))

    if data.get('closing_statement'):
        story.append(Paragraph(data['closing_statement'], conclusion_style))
    else:
        default_closing = (
            "All products are inspected and packaged for shipment prior to leaving the warehouse. "
            "The cardholder has never claimed about the quality of the item. The cardholder has never "
            "tried to return the product according to merchant's Returns & Exchanges Policy. These facts "
            "confirm that this is a clear case of buyer's remorse and so the chargeback should be cancelled."
        )
        story.append(Paragraph(default_closing, conclusion_style))

    build_pdf_with_footer(doc, story)
    print(f"PDF created: {output_path}")
    return output_path


def process_chargeback(paymentid, tenant_name, reason="product_unacceptable"):
    """Standalone processing - used when running this file directly"""
    from shopify_order_screenshot import screenshot_shopify_order
    from shopify_tracking import get_shipping_proof

    payload = {
        "paymentid": paymentid,
        "reason": reason
    }

    print(f"Sending payload: {payload}")
    print(f"Tenant: {tenant_name}")

    r = requests.post(N8N_WEBHOOK, json=payload, timeout=120)

    print(f"Response status: {r.status_code}")
    print(f"Response text: {r.text[:500] if r.text else 'EMPTY'}")

    if not r.text:
        print("ERROR: Empty response from webhook")
        return None

    try:
        response = r.json()
    except Exception as e:
        print(f"JSON parse error: {e}")
        print(f"Raw response: {r.text}")
        return None

    print(f"Response type: {type(response)}")

    data = parse_response(response)

    print(f"Parsed data type: {type(data)}")

    # Use reference from response for filename, fallback to paymentid
    ref = data.get('reference') or paymentid

    # Get screenshots
    screenshots = {}
    if tenant_name and ref:
        print(f"Capturing screenshots for tenant={tenant_name}, reference={ref}")

        # Order screenshot
        order_path = screenshot_shopify_order(tenant_name, ref, "/tmp")
        if order_path:
            screenshots['order_screenshot'] = order_path

        # Tracking screenshot
        tracking_info = get_shipping_proof(tenant_name=tenant_name, reference=ref, output_dir="/tmp")
        if tracking_info and tracking_info.get('screenshot_path'):
            screenshots['tracking_screenshot'] = tracking_info['screenshot_path']

    output_path = f"chargeback_pna_{ref}.pdf"
    generate_pdf(data, output_path, tenant_name, screenshots)

    return output_path


if __name__ == "__main__":
    import sys

    paymentid = sys.argv[1] if len(sys.argv) > 1 else None
    tenant_name = sys.argv[2] if len(sys.argv) > 2 else None
    reason = sys.argv[3] if len(sys.argv) > 3 else "product_unacceptable"

    if not paymentid or not tenant_name:
        print("Usage: python chargeback_generator_pna.py <paymentid> <tenant_name> [reason]")
        print("Example: python chargeback_generator_pna.py abc123 edhardyoriginals")
        sys.exit(1)

    process_chargeback(paymentid, tenant_name, reason)