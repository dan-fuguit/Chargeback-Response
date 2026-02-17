"""
MAIN CHARGEBACK RESPONSE GENERATOR
Sends paymentid to endpoint, receives all data including reason and tenant.
Also extracts session evidence from database and captures Shopify screenshots.

Now with ASYNC parallel task execution for faster processing!

Usage:
    python chargeback_main.py <paymentid>

Example:
    python chargeback_main.py abc123
"""

import sys
import os
import asyncio
import requests
import json
import mysql.connector
from concurrent.futures import ThreadPoolExecutor

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

# Thread pool for blocking operations
executor = ThreadPoolExecutor(max_workers=6)


def get_payment_info(paymentid):
    """Get tenant_id, externalreference, shopname, and payer_mobile from database"""
    try:
        conn = mysql.connector.connect(**DB_CONFIG)
        cursor = conn.cursor()

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
            shopname = result[2]
            store_name = None
            if shopname:
                store_name = shopname.replace('.myshopify.com', '').strip()

            return {
                'tenant_id': result[0],
                'external_reference': result[1],
                'shop_name': store_name,
                'payer_mobile': result[3]
            }
        return None
    except Exception as e:
        print(f"Error getting payment info: {e}")
        return None


# Reason code mapping
FRAUD_REASONS = [
    "unrecognized_transaction", "fraud", "fraudulent", "unauthorized",
    "stolen_card", "card_not_present", "no_authorization",
]

PNR_REASONS = [
    "product_not_received", "merchandise_not_received", "13.1", "delivery_confirmed",
]

PNA_REASONS = [
    "product_unacceptable", "not_as_described", "services_not_rendered", "quality_issue",
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
    """Parse the n8n response"""
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


# ============================================================================
# ASYNC WRAPPER FUNCTIONS
# ============================================================================

async def async_get_session_evidence(paymentid):
    """Extract session evidence from database (async wrapper)"""
    loop = asyncio.get_event_loop()

    def _get_evidence():
        try:
            extractor = SessionEvidenceExtractor()
            evidence = extractor.get_session_evidence(paymentid)
            extractor.close()
            if 'error' in evidence:
                return None
            return evidence
        except Exception as e:
            print(f"  Session evidence error: {e}")
            return None

    return await loop.run_in_executor(executor, _get_evidence)


async def async_screenshot_order(store_name, external_reference, clean_reference):
    """Capture Shopify order screenshot (async wrapper)"""
    loop = asyncio.get_event_loop()

    def _screenshot():
        try:
            if external_reference and store_name:
                order_url = f"https://admin.shopify.com/store/{store_name}/orders/{external_reference}"
                return screenshot_shopify_order_by_url(order_url, clean_reference, SCREENSHOT_DIR)
            else:
                return screenshot_shopify_order(store_name, clean_reference, SCREENSHOT_DIR)
        except Exception as e:
            print(f"  Order screenshot error: {e}")
            return None

    return await loop.run_in_executor(executor, _screenshot)


async def async_screenshot_tracking(tenant_id, tenant_name, clean_reference):
    """Capture tracking screenshot (async wrapper)"""
    loop = asyncio.get_event_loop()

    def _screenshot():
        try:
            return get_shipping_proof(
                tenant_id=tenant_id,
                tenant_name=tenant_name,
                reference=clean_reference,
                output_dir=SCREENSHOT_DIR
            )
        except Exception as e:
            print(f"  Tracking screenshot error: {e}")
            return None

    return await loop.run_in_executor(executor, _screenshot)


async def async_screenshot_identity(paymentid, tenant_id):
    """Capture Fugu identity screenshot (async wrapper)"""
    loop = asyncio.get_event_loop()

    def _screenshot():
        try:
            return screenshot_payment_info(paymentid, tenant_id, SCREENSHOT_DIR)
        except Exception as e:
            print(f"  Identity screenshot error: {e}")
            return None

    return await loop.run_in_executor(executor, _screenshot)


async def async_get_card_details(tenant_id, external_reference, reference):
    """Get card details image (async wrapper)"""
    loop = asyncio.get_event_loop()

    def _get_details():
        try:
            return get_card_details_image(tenant_id, external_reference, reference, SCREENSHOT_DIR)
        except Exception as e:
            print(f"  Card details error: {e}")
            return None

    return await loop.run_in_executor(executor, _get_details)


async def async_get_avs_details(tenant_id, external_reference, reference):
    """Get AVS details image (async wrapper)"""
    loop = asyncio.get_event_loop()

    def _get_details():
        try:
            return get_avs_details_image(tenant_id, external_reference, reference, SCREENSHOT_DIR)
        except Exception as e:
            print(f"  AVS details error: {e}")
            return None

    return await loop.run_in_executor(executor, _get_details)


async def async_get_public_records(payer_mobile):
    """Get public records (async wrapper)"""
    loop = asyncio.get_event_loop()

    def _get_records():
        try:
            return get_public_records(payer_mobile)
        except Exception as e:
            print(f"  Public records error: {e}")
            return None

    return await loop.run_in_executor(executor, _get_records)


async def async_generate_location_map(paymentid):
    """Generate location map (async wrapper)"""
    loop = asyncio.get_event_loop()

    def _generate():
        try:
            return generate_location_map(paymentid, SCREENSHOT_DIR)
        except Exception as e:
            print(f"  Location map error: {e}")
            return None

    return await loop.run_in_executor(executor, _generate)


async def async_call_webhook(paymentid):
    """Call n8n webhook (async wrapper)"""
    loop = asyncio.get_event_loop()

    def _call():
        try:
            r = requests.post(N8N_WEBHOOK, json={"paymentid": paymentid}, timeout=120)
            print(f"Response status: {r.status_code}")
            if r.text:
                return r.json()
            print("ERROR: Empty response from webhook")
            return None
        except Exception as e:
            print(f"  Webhook error: {e}")
            return None

    return await loop.run_in_executor(executor, _call)


# ============================================================================
# MAIN ASYNC PROCESSING
# ============================================================================

async def process_chargeback_async(paymentid):
    """
    Main async entry point - runs tasks in parallel where possible
    """
    print("=" * 50)
    print("CHARGEBACK DISPUTE GENERATOR")
    print("=" * 50)
    print(f"Payment ID: {paymentid}")

    # Step 1: Get payment info from DB (quick, do first)
    print("Getting payment info from database...")
    payment_info = get_payment_info(paymentid)
    tenant_id = payment_info.get('tenant_id') if payment_info else None
    external_reference = payment_info.get('external_reference') if payment_info else None
    shop_name = payment_info.get('shop_name') if payment_info else None
    payer_mobile = payment_info.get('payer_mobile') if payment_info else None

    print(f"Tenant ID: {tenant_id}")
    print(f"External Reference: {external_reference}")
    print(f"Shop Name: {shop_name}")

    # Step 2: Call webhook (must complete before we know reason_type)
    print("Sending request to n8n...")
    response = await async_call_webhook(paymentid)

    if not response:
        return None

    # Parse response
    data, kyc_images, reason, tenant = parse_response(response)
    reference = data.get('reference') or paymentid
    reason_type = get_reason_type(reason)
    clean_reference = str(reference).replace('#', '')

    print(f"Reference: {reference}")
    print(f"Reason: {reason}")
    print(f"Reason Type: {reason_type}")
    print(f"Tenant: {tenant}")
    print(f"Tenant ID: {tenant_id}")
    print(f"KYC Images: {bool(kyc_images.get('id_card') or kyc_images.get('selfie') or kyc_images.get('card'))}")
    print("=" * 50)

    screenshots = {}
    session_evidence = None
    public_records_data = None
    location_map_data = None

    # Step 3: Run parallel tasks based on reason type
    if reason_type == "fraud":
        print("Running parallel tasks for FRAUD case...")

        # Create all tasks
        tasks = {
            'order': async_screenshot_order(shop_name or tenant, external_reference, clean_reference),
            'tracking': async_screenshot_tracking(tenant_id, tenant, clean_reference),
            'identity': async_screenshot_identity(paymentid, tenant_id),
            'card_details': async_get_card_details(tenant_id, external_reference, reference),
            'session': async_get_session_evidence(paymentid),
        }

        # Add location map if needed
        if data.get('location_proof'):
            tasks['location'] = async_generate_location_map(paymentid)

        # Add public records if needed
        if data.get('public_records_proof') and payer_mobile:
            tasks['public_records'] = async_get_public_records(payer_mobile)

        # Check if AVS details needed
        payment_proof = data.get('payment_proof', {})
        payment_text = payment_proof.get('text', '') if isinstance(payment_proof, dict) else str(payment_proof)
        has_avs_match = 'AVS' in payment_text.upper() and (
                    'Y' in payment_text or 'full match' in payment_text.lower() or 'match' in payment_text.lower())

        if has_avs_match:
            tasks['avs'] = async_get_avs_details(tenant_id, external_reference, reference)

        # Run all tasks in parallel
        print(f"  Running {len(tasks)} tasks in parallel...")
        results = await asyncio.gather(*tasks.values(), return_exceptions=True)
        results_dict = dict(zip(tasks.keys(), results))

        # Process results
        if results_dict.get('order') and not isinstance(results_dict['order'], Exception):
            screenshots['order_screenshot'] = results_dict['order']
            print(f"  ✓ Order screenshot: {results_dict['order']}")

        tracking_info = results_dict.get('tracking')
        if tracking_info and not isinstance(tracking_info, Exception) and tracking_info.get('screenshot_path'):
            screenshots['tracking_screenshot'] = tracking_info['screenshot_path']
            screenshots['tracking_url'] = tracking_info.get('tracking_url')
            print(f"  ✓ Tracking screenshot: {tracking_info['screenshot_path']}")

        if results_dict.get('identity') and not isinstance(results_dict['identity'], Exception):
            screenshots['identity_screenshot'] = results_dict['identity']
            print(f"  ✓ Identity screenshot: {results_dict['identity']}")

        card_details = results_dict.get('card_details')
        if card_details and not isinstance(card_details, Exception) and card_details.get('screenshot_path'):
            screenshots['card_details_screenshot'] = card_details['screenshot_path']
            print(f"  ✓ Card details: {card_details['screenshot_path']}")

        session_evidence = results_dict.get('session')
        if session_evidence and not isinstance(session_evidence, Exception):
            stats = session_evidence.get('_raw_data', {}).get('session_stats', {})
            print(f"  ✓ Session evidence: {stats.get('total_sessions', 0)} sessions")

        location_result = results_dict.get('location')
        if location_result and not isinstance(location_result, Exception) and location_result.get('screenshot_path'):
            location_map_data = location_result
            screenshots['location_screenshot'] = location_result['screenshot_path']
            print(f"  ✓ Location map: {location_result['screenshot_path']}")

        pr_result = results_dict.get('public_records')
        if pr_result and not isinstance(pr_result, Exception):
            public_records_data = pr_result
            public_records_data['_phone_number'] = payer_mobile
            print(f"  ✓ Public records: {pr_result.get('name', 'Unknown')}")

        avs_result = results_dict.get('avs')
        if avs_result and not isinstance(avs_result, Exception) and avs_result.get('screenshot_path'):
            screenshots['avs_screenshot'] = avs_result['screenshot_path']
            print(f"  ✓ AVS details: {avs_result['screenshot_path']}")

        output_path = f"bulk_responses/chargeback_fraud_{reference}.pdf"
        os.makedirs("bulk_responses", exist_ok=True)
        generate_fraud_pdf(data, kyc_images, output_path, session_evidence, tenant, screenshots, public_records_data,
                           location_map_data)

    elif reason_type == "pnr":
        print("Running parallel tasks for PNR case...")

        tasks = {
            'order': async_screenshot_order(shop_name or tenant, external_reference, clean_reference),
            'tracking': async_screenshot_tracking(tenant_id, tenant, clean_reference),
            'card_details': async_get_card_details(tenant_id, external_reference, reference),
        }

        print(f"  Running {len(tasks)} tasks in parallel...")
        results = await asyncio.gather(*tasks.values(), return_exceptions=True)
        results_dict = dict(zip(tasks.keys(), results))

        if results_dict.get('order') and not isinstance(results_dict['order'], Exception):
            screenshots['order_screenshot'] = results_dict['order']
            print(f"  ✓ Order screenshot: {results_dict['order']}")

        tracking_info = results_dict.get('tracking')
        if tracking_info and not isinstance(tracking_info, Exception) and tracking_info.get('screenshot_path'):
            screenshots['tracking_screenshot'] = tracking_info['screenshot_path']
            screenshots['tracking_url'] = tracking_info.get('tracking_url')
            print(f"  ✓ Tracking screenshot: {tracking_info['screenshot_path']}")

        card_details = results_dict.get('card_details')
        if card_details and not isinstance(card_details, Exception) and card_details.get('screenshot_path'):
            screenshots['card_details_screenshot'] = card_details['screenshot_path']
            print(f"  ✓ Card details: {card_details['screenshot_path']}")

        output_path = f"bulk_responses/chargeback_pnr_{reference}.pdf"
        os.makedirs("bulk_responses", exist_ok=True)
        generate_pnr_pdf(data, output_path, tenant, screenshots)

    else:  # pna
        print("Running parallel tasks for PNA case...")

        tasks = {
            'order': async_screenshot_order(shop_name or tenant, external_reference, clean_reference),
            'tracking': async_screenshot_tracking(tenant_id, tenant, clean_reference),
            'card_details': async_get_card_details(tenant_id, external_reference, reference),
        }

        print(f"  Running {len(tasks)} tasks in parallel...")
        results = await asyncio.gather(*tasks.values(), return_exceptions=True)
        results_dict = dict(zip(tasks.keys(), results))

        if results_dict.get('order') and not isinstance(results_dict['order'], Exception):
            screenshots['order_screenshot'] = results_dict['order']
            print(f"  ✓ Order screenshot: {results_dict['order']}")

        tracking_info = results_dict.get('tracking')
        if tracking_info and not isinstance(tracking_info, Exception) and tracking_info.get('screenshot_path'):
            screenshots['tracking_screenshot'] = tracking_info['screenshot_path']
            screenshots['tracking_url'] = tracking_info.get('tracking_url')
            print(f"  ✓ Tracking screenshot: {tracking_info['screenshot_path']}")

        card_details = results_dict.get('card_details')
        if card_details and not isinstance(card_details, Exception) and card_details.get('screenshot_path'):
            screenshots['card_details_screenshot'] = card_details['screenshot_path']
            print(f"  ✓ Card details: {card_details['screenshot_path']}")

        output_path = f"bulk_responses/chargeback_pna_{reference}.pdf"
        os.makedirs("bulk_responses", exist_ok=True)
        generate_pna_pdf(data, output_path, tenant, screenshots)

    return output_path


def process_chargeback(paymentid):
    """Sync wrapper for async function"""
    return asyncio.run(process_chargeback_async(paymentid))


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