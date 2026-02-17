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
        has_avs_match = 'AVS' in payment_text.upper() and (
                    'Y' in payment_text or 'full match' in payment_text.lower() or 'match' in payment_text.lower())

        if has_avs_match:
            print("AVS match detected, generating AVS verification image...")
            avs_details_data = get_avs_details_image(tenant_id, external_reference, reference, SCREENSHOT_DIR)
            if avs_details_data and avs_details_data.get('screenshot_path'):
                screenshots['avs_screenshot'] = avs_details_data['screenshot_path']
                print(f"  AVS details: {avs_details_data['screenshot_path']}")
            else:
                print("  Failed to generate AVS details image")

        output_path = f"bulk_responses5/chargeback_fraud_{reference}.pdf"
        os.makedirs("bulk_responses5", exist_ok=True)
        generate_fraud_pdf(data, kyc_images, output_path, session_evidence, tenant, screenshots, public_records_data,
                           location_map_data)

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

        output_path = f"bulk_responses5/chargeback_pnr_{reference}.pdf"
        os.makedirs("bulk_responses5", exist_ok=True)
        generate_pnr_pdf(data, output_path, tenant, screenshots)

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

        output_path = f"bulk_responses5/chargeback_pna_{reference}.pdf"
        os.makedirs("bulk_responses5", exist_ok=True)
        generate_pna_pdf(data, output_path, tenant, screenshots)

    return output_path


def process_bulk(payment_ids):
    """
    Process multiple chargebacks in bulk.

    Args:
        payment_ids: List of payment IDs to process

    Returns:
        Dict with 'success' and 'failed' lists
    """
    results = {
        'success': [],
        'failed': []
    }

    total = len(payment_ids)

    for i, paymentid in enumerate(payment_ids, 1):
        print(f"\n{'=' * 60}")
        print(f"Processing {i}/{total}: {paymentid}")
        print('=' * 60)

        try:
            result = process_chargeback(paymentid)
            if result:
                results['success'].append({'id': paymentid, 'output': result})
                print(f"✓ SUCCESS: {result}")
            else:
                results['failed'].append({'id': paymentid, 'error': 'No output generated'})
                print(f"✗ FAILED: No output generated")
        except Exception as e:
            results['failed'].append({'id': paymentid, 'error': str(e)})
            print(f"✗ FAILED: {e}")

    # Print summary
    print(f"\n{'=' * 60}")
    print("BULK PROCESSING COMPLETE")
    print('=' * 60)
    print(f"Total: {total}")
    print(f"Success: {len(results['success'])}")
    print(f"Failed: {len(results['failed'])}")

    if results['failed']:
        print(f"\nFailed IDs:")
        for item in results['failed']:
            print(f"  - {item['id']}: {item['error']}")

    return results


# =============================================================================
# BULK PAYMENT IDS - ADD YOUR IDS HERE
# =============================================================================
PAYMENT_IDS = [
   "a7a4d93c-72d3-4943-88b3-425e4e98b894",
"8aa80759-0625-4727-872b-62a0639c99c4",
"7a030466-1613-4223-9364-96065f51b6f0",
"78f28c31-03a3-43d6-90c6-f9da9ac39ce0",
"3d03315a-05ee-4607-800f-e297f5a83da1",
"5ed17e64-a7bb-417f-849c-797ba4f087b3",
"3cc7d774-1eb0-4084-9cf3-387a1f2795b7",
"4db6c9a4-1b2a-4576-92aa-2c3f36e26519",
"7440ea90-d17d-404f-947b-c55b204dcbd9",
"b0fdfa30-390b-4335-be93-bc4399085d4b",
"c30089e2-8e45-4e39-bd7f-39c6c2269020",
"8f656f47-7173-4f37-bc2a-0445e790f9dc",
"471716aa-4c1f-4a67-9301-5cd37ff602ab",
"504e7728-3ec8-4894-b960-52db06628351",
"a1f7f258-57bc-4962-9d63-a66c82b849af",
"18bbd5f2-5b73-458b-8a72-5db44a00f5e0",
"72e04525-7dc5-47c0-af04-0182bb7b8316",
"a3702b7a-1b99-4052-969c-016ea3ab278c",
"bd4f0eb3-6320-4a28-9d4c-a449fa2f9e0e",
"4ca6b268-af0b-423b-a08e-094c180c4965",
"0b64616e-68ac-4355-b206-20c2d900d483",
"c11684e3-9131-46de-8540-4cdc71d22f2b",
"bf6dc4fb-a36e-4094-abc5-57a848fc9c5d",
"96fce0a1-49c4-4c6e-89db-a202461c9dc5",
"4a9d286e-670b-4fb1-b291-9ed72b5f2c86",
"2bf932ef-b7ba-47f7-8d31-8df46ee8e326",
"ead423ac-6778-4dff-91e1-dbb53d6ce81b",
"03da3f21-1386-425c-be9f-ca63b9a82919",
"79353cf2-80ac-4d0a-9be4-45406e295d91",
"b410cf2f-c8df-449a-9c0a-23e65493ebc5",
"fa52e865-f20b-4c84-931f-892196b7bda9",
"a566bf68-72e0-4ed0-904b-72e72cec0470",
"36f24f3a-a165-4172-97f0-c4426cb0a9e1",
"f674208f-b8b5-4f63-90b4-4796e838e6bb",
"4d5e26d0-3010-4a3d-a70f-299cb3de0ed7",
"4b2d08bb-b0dc-4ec8-b589-ac3839a98512",
"64b72b50-36eb-4ad3-bdfc-f9bb8be92cd6",
"58a4237e-aaec-4363-9b36-77e9f7e72724",
"9cb97eac-513f-41e1-9ba5-51e892d838c1"

]

    # Add more IDs as needed...


if __name__ == "__main__":
    # Process all IDs in the list
    results = process_bulk(PAYMENT_IDS)

    if results['failed']:
        sys.exit(1)