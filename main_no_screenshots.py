"""
MAIN CHARGEBACK RESPONSE GENERATOR (NO SCREENSHOTS)
Same as Main.py but skips ALL Playwright/screenshot usage.
Blank spaces are left where screenshots would appear in the PDF.

Still performs: DB queries, webhook call, session evidence, public records,
and location analysis (text/distances only, no map image).

Usage:
    python main_no_screenshots.py <paymentid>

Example:
    python main_no_screenshots.py abc123
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
from session_evidence_extractor import SessionEvidenceExtractor
from public_records import get_public_records, format_public_records_for_pdf
from map_generator import get_location_data, analyze_locations

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


def get_location_analysis(paymentid):
    """
    Get location analysis (distances/summary) without generating a map image.
    Uses only DB queries and math - no Playwright.

    Returns:
        Dict with 'screenshot_path' (None), 'analysis', and 'locations', or None
    """
    locations = get_location_data(paymentid)
    if not locations:
        print("  No location data available")
        return None

    analysis = analyze_locations(locations, max_relevant_distance=100)

    if len(analysis['relevant_locations']) < 2:
        print("  Not enough relevant locations for analysis")
        return {
            'screenshot_path': None,
            'analysis': analysis,
            'locations': locations
        }

    print(f"  Location analysis: {analysis['summary']}")
    return {
        'screenshot_path': None,
        'analysis': analysis,
        'locations': locations
    }


def process_chargeback(paymentid):
    """
    Main entry point (no screenshots version)

    Args:
        paymentid: Payment ID to dispute

    Returns:
        Path to generated PDF
    """

    payload = {"paymentid": paymentid}

    print("=" * 50)
    print("CHARGEBACK DISPUTE GENERATOR (NO SCREENSHOTS)")
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

    # No screenshots - pass empty dict, PDF generators handle None gracefully
    screenshots = {}

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

        print("Skipping Shopify screenshots (no-screenshots mode)")
        print("Skipping Fugu identity screenshot (no-screenshots mode)")
        print("Skipping card details image (no-screenshots mode)")

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

        # Get location analysis (text only, no map image) if location_proof exists
        location_map_data = None
        if data.get('location_proof'):
            print("Getting location analysis (no map image)...")
            location_map_data = get_location_analysis(paymentid)

        output_path = f"chargeback_fraud_{reference}.pdf"
        generate_fraud_pdf(data, kyc_images, output_path, session_evidence, tenant, screenshots, public_records_data, location_map_data)

    elif reason_type == "pnr":
        print("Skipping Shopify screenshots (no-screenshots mode)")
        print("Skipping card details image (no-screenshots mode)")

        output_path = f"pnr_test/chargeback_pnr_{reference}.pdf"

        # Create pnr_test folder if it doesn't exist
        os.makedirs("pnr_test", exist_ok=True)

        generate_pnr_pdf(data, output_path, tenant, screenshots)

    else:  # pna
        print("Skipping Shopify screenshots (no-screenshots mode)")
        print("Skipping card details image (no-screenshots mode)")

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
