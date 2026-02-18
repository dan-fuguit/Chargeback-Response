"""
MAIN CHARGEBACK RESPONSE GENERATOR
Sends paymentid to endpoint, receives all data including reason and tenant.
Also extracts session evidence from database and captures Shopify screenshots.

Usage:
    python chargeback_main.py <paymentid>

Example:
    python chargeback_main.py abc123
"""

import sys
import os
import requests
import json
import mysql.connector

# Add current directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Import generators
from chargeback_generator_fraud import generate_pdf as generate_fraud_pdf
from chargeback_generator_pnr import generate_pdf as generate_pnr_pdf
from chargeback_generator_pna import generate_pdf as generate_pna_pdf
from chargeback_generator_cnp import generate_pdf as generate_cnp_pdf
from session_evidence_extractor import SessionEvidenceExtractor
from shopify_order_screenshot import screenshot_shopify_order, screenshot_shopify_order_by_url
from shopify_tracking import get_shipping_proof
from fugu_screenshot import screenshot_payment_info
from public_records import get_public_records, format_public_records_for_pdf
from map_generator import generate_location_map
from card_details import get_card_details_image, get_avs_details_image

# Configuration
N8N_WEBHOOK = "https://dan-fugu.app.n8n.cloud/webhook/55614aa6-0d64-4390-ab2c-d595b6e0fda4"
SCREENSHOT_DIR = "/tmp"

# Database config
DB_CONFIG = {
    'host': 'fugu-sql-prod-rep.mysql.database.azure.com',
    'database': 'fuguprod',
    'user': 'geckoboard',
    'password': 'UrxP3FmJ+z1bF1Xjs<*%'
}


def get_payment_info(paymentid):
    """Get tenant_id, externalreference, shopname, and payer_mobile from database"""
    try:
        conn = mysql.connector.connect(**DB_CONFIG)
        cursor = conn.cursor()

        # Get payment info and join with shopifyintegration to get shopname
        query = """
            SELECT p.Tenants_tntid, p.externalreference, s.shopname, p.payer_mobile 
            FROM payments p
            LEFT JOIN shopifyintegration s ON p.Tenants_tntid = s.tenantid
            WHERE p.paymentid = %s
        """
        cursor.execute(query, (paymentid,))
        result = cursor.fetchone()
        cursor.close()
        conn.close()

        if result:
            # shopname is like 'edhardyoriginals.myshopify.com' - extract just the store name
            shopname = result[2]
            store_name = None
            if shopname:
                store_name = shopname.replace('.myshopify.com', '').strip()

            return {
                'tenant_id': result[0],
                'external_reference': result[1],  # Shopify order ID
                'shop_name': store_name,  # Store name for URL building
                'payer_mobile': result[3]  # Phone number for public records lookup
            }
        return None
    except Exception as e:
        print(f"Error getting payment info: {e}")
        return None

# Reason code mapping
FRAUD_REASONS = [
    "unrecognized_transaction",
    "fraud",
    "fraudulent",
    "unauthorized",
    "stolen_card",
    "card_not_present",
    "no_authorization",
]

# Product Not Received - simple delivery proof only
PNR_REASONS = [
    "product_not_received",
    "merchandise_not_received",
    "13.1",
    "delivery_confirmed",
]

# Product Not Acceptable - needs return policy
PNA_REASONS = [
    "product_unacceptable",
    "not_as_described",
    "services_not_rendered",
    "quality_issue",
]

# Credit Not Processed - same layout as PNA + payment verification image before shipping
CNP_REASONS = [
    "credit_not_processed",
    "credit_not_issued",
    "refund_not_processed",
]


def get_reason_type(reason):
    """Determine which generator to use based on reason code"""
    if not reason:
        return "fraud"

    reason_lower = reason.lower().strip().replace(" ", "_").replace("-", "_")

    if reason_lower in FRAUD_REASONS:
        return "fraud"
    elif reason_lower in PNR_REASONS:
        return "pnr"
    elif reason_lower in PNA_REASONS:
        return "pna"
    elif reason_lower in CNP_REASONS:
        return "cnp"
    else:
        print(f"Warning: Unknown reason '{reason}', defaulting to fraud generator")
        return "fraud"


def parse_response(response):
    """Parse the n8n response to extract LLM data, KYC images, reason, and tenant"""
    llm_data = {}
    kyc_images = {'id_card': None, 'selfie': None, 'card': None}
    reason = None
    tenant = None

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

        if 'kyc_images' in response:
            kyc_images = response['kyc_images']

        reason = response.get('reason') or llm_data.get('chargeback_reason')
        tenant = response.get('tenant') or response.get('tenant_name') or llm_data.get('tenant') or 'default'

    return llm_data, kyc_images, reason, tenant


def get_session_evidence(paymentid):
    """Extract session evidence from database"""
    try:
        extractor = SessionEvidenceExtractor()
        evidence = extractor.get_session_evidence(paymentid)
        extractor.close()

        if 'error' in evidence:
            print(f"Session evidence warning: {evidence['error']}")
            return None

        return evidence
    except Exception as e:
        print(f"Session evidence error: {e}")
        return None


def get_shopify_screenshots(tenant_id, tenant_name, reference, external_reference=None, shop_name=None):
    """
    Capture Shopify order and tracking screenshots.

    Args:
        tenant_id: Tenant ID (for tracking API lookup)
        tenant_name: Tenant/store name (from n8n, used as fallback)
        reference: Order reference number
        external_reference: Shopify order ID (e.g., 6448566206690)
        shop_name: Shop name from database (e.g., edhardyoriginals)

    Returns:
        dict with 'order_screenshot' and 'tracking_screenshot' paths
    """
    screenshots = {
        'order_screenshot': None,
        'tracking_screenshot': None
    }

    if not reference:
        print("  Missing reference for Shopify screenshots")
        return screenshots

    # Clean reference
    clean_reference = str(reference).replace('#', '')

    # Use shop_name from DB, fallback to tenant_name from n8n
    store_name = shop_name or tenant_name

    # 1. Order page screenshot - use external_reference ID to build direct URL
    print(f"  Capturing Shopify order screenshot...")
    try:
        if external_reference and store_name:
            # Build direct URL from external_reference ID
            # https://admin.shopify.com/store/edhardyoriginals/orders/6448566206690
            order_url = f"https://admin.shopify.com/store/{store_name}/orders/{external_reference}"
            order_path = screenshot_shopify_order_by_url(order_url, clean_reference, SCREENSHOT_DIR)
        else:
            # Fall back to search method
            order_path = screenshot_shopify_order(store_name, clean_reference, SCREENSHOT_DIR)

        if order_path:
            screenshots['order_screenshot'] = order_path
            print(f"    Order screenshot: {order_path}")
        else:
            print("    Failed to capture order screenshot")
    except Exception as e:
        print(f"    Order screenshot error: {e}")

    # 2. Tracking page screenshot (uses tenant_id for DB lookup)
    print(f"  Capturing tracking screenshot...")
    try:
        tracking_info = get_shipping_proof(
            tenant_id=tenant_id,
            tenant_name=tenant_name,
            reference=clean_reference,
            output_dir=SCREENSHOT_DIR
        )
        if tracking_info and tracking_info.get('screenshot_path'):
            screenshots['tracking_screenshot'] = tracking_info['screenshot_path']
            screenshots['tracking_url'] = tracking_info.get('tracking_url')
            print(f"    Tracking screenshot: {tracking_info['screenshot_path']}")
            print(f"    Carrier: {tracking_info.get('tracking_company')}")
            print(f"    Tracking #: {tracking_info.get('tracking_number')}")
            print(f"    Tracking URL: {tracking_info.get('tracking_url')}")
        else:
            print("    No tracking info found")
    except Exception as e:
        print(f"    Tracking screenshot error: {e}")

    return screenshots


def process_chargeback(paymentid):
    """
    Main entry point

    Args:
        paymentid: Payment ID to dispute

    Returns:
        Path to generated PDF
    """

    payload = {"paymentid": paymentid}

    print("=" * 50)
    print("CHARGEBACK DISPUTE GENERATOR")
    print("=" * 50)
    print(f"Payment ID: {paymentid}")

    # Get tenant_id and external_reference from database
    print("Getting payment info from database...")
    payment_info = get_payment_info(paymentid)
    tenant_id = payment_info.get('tenant_id') if payment_info else None
    external_reference = payment_info.get('external_reference') if payment_info else None
    shop_name = payment_info.get('shop_name') if payment_info else None
    print(f"Tenant ID: {tenant_id}")
    print(f"External Reference: {external_reference}")
    print(f"Shop Name: {shop_name}")

    print("Sending request to n8n...")
    r = requests.post(N8N_WEBHOOK, json=payload, timeout=120)
    print(f"Response status: {r.status_code}")

    if not r.text:
        print("ERROR: Empty response from webhook")
        return None

    try:
        response = r.json()
    except Exception as e:
        print(f"JSON parse error: {e}")
        return None

    # Parse response
    data, kyc_images, reason, tenant = parse_response(response)

    reference = data.get('reference') or paymentid
    reason_type = get_reason_type(reason)

    print(f"Reference: {reference}")
    print(f"Reason: {reason}")
    print(f"Reason Type: {reason_type}")
    print(f"Tenant: {tenant}")
    print(f"Tenant ID: {tenant_id}")
    print(f"KYC Images: {bool(kyc_images.get('id_card') or kyc_images.get('selfie') or kyc_images.get('card'))}")
    print("=" * 50)

    # Route to correct generator
    if reason_type == "fraud":
        # Get session evidence for fraud cases
        print("Extracting session evidence for fraud case...")
        session_evidence = get_session_evidence(paymentid)
        if session_evidence and 'error' not in session_evidence:
            stats = session_evidence.get('_raw_data', {}).get('session_stats', {})
            print(f"  Sessions found: {stats.get('total_sessions', 0)}")
        else:
            print("  No session evidence found")
            session_evidence = None

        # Get Shopify screenshots for fraud cases too
        print("Capturing Shopify screenshots for fraud case...")
        screenshots = get_shopify_screenshots(tenant_id, tenant, reference, external_reference, shop_name)

        # Get Fugu identity screenshot for fraud cases
        print("Capturing Fugu identity screenshot...")
        identity_path = screenshot_payment_info(paymentid, tenant_id, SCREENSHOT_DIR)
        if identity_path:
            screenshots['identity_screenshot'] = identity_path
            print(f"  Identity screenshot: {identity_path}")
        else:
            print("  Failed to capture identity screenshot")

        # Get public records if LLM indicated a match
        public_records_data = None
        if data.get('public_records_proof'):
            print("Public records match indicated by LLM, fetching from Redis...")
            payer_mobile = payment_info.get('payer_mobile') if payment_info else None
            if payer_mobile:
                public_records_data = get_public_records(payer_mobile)
                if public_records_data:
                    # Add phone number to the data for display
                    public_records_data['_phone_number'] = payer_mobile
                    print(f"  Public records found: {public_records_data.get('name', 'Unknown')}")
                else:
                    print("  No public records found in Redis")
            else:
                print("  No payer_mobile in payment info")

        # Generate location map if location_proof exists
        location_map_data = None
        if data.get('location_proof'):
            print("Generating location verification map...")
            location_map_data = generate_location_map(paymentid, SCREENSHOT_DIR)
            if location_map_data and location_map_data.get('screenshot_path'):
                screenshots['location_screenshot'] = location_map_data['screenshot_path']
                print(f"  Location map: {location_map_data['screenshot_path']}")
                print(f"  Distances: {location_map_data['analysis']['summary']}")
            else:
                print("  Failed to generate location map")

        # Get card details image for payment proof
        print("Generating card details image...")
        card_details_data = get_card_details_image(tenant_id, external_reference, reference, SCREENSHOT_DIR)
        if card_details_data and card_details_data.get('screenshot_path'):
            screenshots['card_details_screenshot'] = card_details_data['screenshot_path']
            print(f"  Card details: {card_details_data['screenshot_path']}")
        else:
            print("  Failed to generate card details image")

        # Get AVS details image if payment_proof mentions AVS match
        payment_proof = data.get('payment_proof', {})
        payment_text = payment_proof.get('text', '') if isinstance(payment_proof, dict) else str(payment_proof)

        # Check if AVS Y match is indicated
        has_avs_match = 'AVS' in payment_text.upper() and ('Y' in payment_text or 'full match' in payment_text.lower() or 'match' in payment_text.lower())

        if has_avs_match:
            print("AVS match detected, generating AVS verification image...")
            avs_details_data = get_avs_details_image(tenant_id, external_reference, reference, SCREENSHOT_DIR)
            if avs_details_data and avs_details_data.get('screenshot_path'):
                screenshots['avs_screenshot'] = avs_details_data['screenshot_path']
                print(f"  AVS details: {avs_details_data['screenshot_path']}")
            else:
                print("  Failed to generate AVS details image")

        output_path = f"chargeback_fraud_{reference}.pdf"
        generate_fraud_pdf(data, kyc_images, output_path, session_evidence, tenant, screenshots, public_records_data, location_map_data)

    elif reason_type == "pnr":
        # PNR - Get Shopify screenshots for delivery proof
        print("Capturing Shopify screenshots for PNR case...")
        screenshots = get_shopify_screenshots(tenant_id, tenant, reference, external_reference, shop_name)

        # Get card details image for payment proof
        print("Generating card details image...")
        card_details_data = get_card_details_image(tenant_id, external_reference, reference, SCREENSHOT_DIR)
        if card_details_data and card_details_data.get('screenshot_path'):
            screenshots['card_details_screenshot'] = card_details_data['screenshot_path']
            print(f"  Card details: {card_details_data['screenshot_path']}")
        else:
            print("  Failed to generate card details image")

        output_path = f"pnr_test/chargeback_pnr_{reference}.pdf"

        # Create pnr_test folder if it doesn't exist
        import os
        os.makedirs("pnr_test", exist_ok=True)

        generate_pnr_pdf(data, output_path, tenant, screenshots)

    elif reason_type == "cnp":
        # CNP - Same as PNA but with payment verification image before shipping
        print("Capturing Shopify screenshots for CNP case...")
        screenshots = get_shopify_screenshots(tenant_id, tenant, reference, external_reference, shop_name)

        # Get card details image for payment verification section
        print("Generating card details image...")
        card_details_data = get_card_details_image(tenant_id, external_reference, reference, SCREENSHOT_DIR)
        if card_details_data and card_details_data.get('screenshot_path'):
            screenshots['card_details_screenshot'] = card_details_data['screenshot_path']
            print(f"  Card details: {card_details_data['screenshot_path']}")
        else:
            print("  Failed to generate card details image")

        output_path = f"chargeback_cnp_{reference}.pdf"
        generate_cnp_pdf(data, output_path, tenant, screenshots)

    else:  # pna
        # PNA - Get Shopify screenshots + return policy
        print("Capturing Shopify screenshots for PNA case...")
        screenshots = get_shopify_screenshots(tenant_id, tenant, reference, external_reference, shop_name)

        # Get card details image for payment proof
        print("Generating card details image...")
        card_details_data = get_card_details_image(tenant_id, external_reference, reference, SCREENSHOT_DIR)
        if card_details_data and card_details_data.get('screenshot_path'):
            screenshots['card_details_screenshot'] = card_details_data['screenshot_path']
            print(f"  Card details: {card_details_data['screenshot_path']}")
        else:
            print("  Failed to generate card details image")

        output_path = f"chargeback_pna_{reference}.pdf"
        generate_pna_pdf(data, output_path, tenant, screenshots)

    return output_path


if __name__ == "__main__":
    paymentid = sys.argv[1] if len(sys.argv) > 1 else '3f72dd4d-d5bf-4219-a888-ef1023a3e0e7'

    result = process_chargeback(paymentid)

    if result:
        print(f"\n{'=' * 50}")
        print(f"SUCCESS: {result}")
        print("=" * 50)
    else:
        print("\nFAILED to generate PDF")
        sys.exit(1)

        # fraud '4c85a19d-7f55-4010-ad3c-a6b0e88d0560'
        # pnr 'b2357a1d-3570-4919-9139-21a5640ea61a'
        # ef420 '700e7b9b-d1e3-4258-afeb-57737c691a08'