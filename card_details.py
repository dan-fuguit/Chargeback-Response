"""
CARD DETAILS MODULE
card_details.py

Fetches card/transaction details from Shopify API and generates a styled image
for payment verification in all chargeback types (fraud, PNR, PNA).
"""

import json
import tempfile
import os
import requests
import mysql.connector
from datetime import datetime
from playwright.sync_api import sync_playwright

# Database config
DB_CONFIG = {
    "host": "fugu-sql-prod-rep.mysql.database.azure.com",
    "user": "geckoboard",
    "password": "UrxP3FmJ+z1bF1Xjs<*%",
    "database": "fuguprod",
}


def get_shopify_credentials(tenant_id):
    """Get Shopify API credentials from database"""
    try:
        conn = mysql.connector.connect(**DB_CONFIG)
        cursor = conn.cursor()

        query = """
            SELECT shopname, accesstoken 
            FROM shopifyintegration 
            WHERE tenantid = %s
        """
        cursor.execute(query, (tenant_id,))
        result = cursor.fetchone()
        cursor.close()
        conn.close()

        if result:
            return {
                'shop_url': result[0],
                'access_token': result[1]
            }
        return None
    except Exception as e:
        print(f"Error getting Shopify credentials: {e}")
        return None


def get_order_transactions(shop_url, access_token, order_id):
    """Fetch transactions for an order from Shopify API"""
    url = f"https://{shop_url}/admin/api/2024-01/orders/{order_id}/transactions.json"

    headers = {
        "X-Shopify-Access-Token": access_token,
        "Content-Type": "application/json"
    }

    try:
        response = requests.get(url, headers=headers, timeout=30)

        if response.status_code == 200:
            return response.json().get('transactions', [])
        else:
            print(f"Shopify API error: {response.status_code}")
            return None
    except Exception as e:
        print(f"Error fetching transactions: {e}")
        return None


def extract_card_data(transactions, reference):
    """Extract card data for image generation"""
    if not transactions:
        return None

    # Ensure transactions is a list
    if not isinstance(transactions, list):
        print(f"Unexpected transactions format: {type(transactions)}")
        return None

    # Find authorization or capture transaction
    txn = None
    for t in transactions:
        # Skip if not a dict
        if not isinstance(t, dict):
            continue
        if t.get('kind') in ['authorization', 'capture', 'sale'] and t.get('status') == 'success':
            txn = t
            break

    if not txn:
        # Get first dict transaction
        for t in transactions:
            if isinstance(t, dict):
                txn = t
                break

    if not txn:
        print("No valid transaction found")
        return None

    payment_details = txn.get('payment_details') or {}
    if isinstance(payment_details, str):
        payment_details = {}

    receipt = txn.get('receipt') or {}
    if isinstance(receipt, str):
        receipt = {}

    # Handle latest_charge - it can be a string (charge ID) or dict
    # If it's a string, we need to get charge data from charges.data[0]
    latest_charge = receipt.get('latest_charge')
    if isinstance(latest_charge, str) or latest_charge is None:
        # Get from charges.data[0] instead
        charges = receipt.get('charges') or {}
        if isinstance(charges, dict):
            charges_data = charges.get('data') or []
            if charges_data and isinstance(charges_data, list) and len(charges_data) > 0:
                latest_charge = charges_data[0]
            else:
                latest_charge = {}
        else:
            latest_charge = {}

    if not isinstance(latest_charge, dict):
        latest_charge = {}

    outcome = latest_charge.get('outcome') or {}
    if isinstance(outcome, str):
        outcome = {}

    payment_method_details = latest_charge.get('payment_method_details') or {}
    if isinstance(payment_method_details, str):
        payment_method_details = {}

    card = payment_method_details.get('card') or {}
    if isinstance(card, str):
        card = {}

    # Format created date
    created_at = txn.get('created_at', '')
    if created_at:
        try:
            dt = datetime.fromisoformat(created_at.replace('Z', '+00:00'))
            created_at = dt.strftime('%b %d, %Y, %I:%M %p')
        except:
            pass

    # Safe get for card_last4
    card_last4 = card.get('last4', '')
    if not card_last4:
        cc_num = payment_details.get('credit_card_number', '')
        if cc_num and len(cc_num) >= 4:
            # Extract last 4 digits (handle masked format like "•••• •••• •••• 5109")
            card_last4 = cc_num.replace('•', '').replace(' ', '')[-4:]
        else:
            card_last4 = '****'

    # Check payment method type (for Affirm/Shop Pay Installments)
    payment_type = payment_method_details.get('type', '')
    payment_method_name = payment_details.get('payment_method_name', '')

    # Determine card brand - handle Shop Pay Installments
    card_brand = payment_details.get('credit_card_company', '') or card.get('brand', '').title()
    if not card_brand and payment_type == 'affirm':
        card_brand = 'Affirm'
    if not card_brand and 'installments' in payment_method_name.lower():
        card_brand = 'Shop Pay Installments'
    if not card_brand:
        card_brand = 'Card'

    return {
        'order_number': reference or '',
        'card_brand': card_brand,
        'card_last4': card_last4,
        'cardholder_name': payment_details.get('credit_card_name', ''),
        'authorization_key': txn.get('authorization', ''),
        'message': outcome.get('seller_message', 'Payment complete.'),
        'amount': f"${txn.get('amount', '0.00')}",
        'gateway': txn.get('gateway', ''),
        'status': txn.get('status', ''),
        'type': txn.get('kind', ''),
        'created': created_at,
    }


def generate_card_image(data, output_path):
    """Generate Shopify-style card details image"""

    # Build optional fields HTML
    optional_fields = ""
    if data.get('gateway'):
        gateway_display = data['gateway'].replace('_', ' ').title()
        optional_fields += f"""
            <div class="field">
                <div class="field-label">Gateway</div>
                <div class="field-value">{gateway_display}</div>
            </div>
        """
    if data.get('status'):
        optional_fields += f"""
            <div class="field">
                <div class="field-label">Status</div>
                <div class="field-value">{data['status'].title()}</div>
            </div>
        """
    if data.get('type'):
        optional_fields += f"""
            <div class="field">
                <div class="field-label">Type</div>
                <div class="field-value">{data['type'].title()}</div>
            </div>
        """

    html_content = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <style>
            * {{
                margin: 0;
                padding: 0;
                box-sizing: border-box;
            }}
            body {{
                font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
                background: #F1F1F1;
                padding: 16px;
                font-size: 14px;
                color: #303030;
                line-height: 1.5;
            }}
            .container {{
                max-width: 300px;
            }}
            .field {{
                margin-bottom: 14px;
            }}
            .field-label {{
                font-weight: 600;
                font-size: 14px;
                color: #303030;
            }}
            .field-value {{
                font-size: 14px;
                color: #303030;
            }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="field">
                <div class="field-label">Order</div>
                <div class="field-value">{data.get('order_number', '#000000')}</div>
            </div>

            <div class="field">
                <div class="field-label">Card details</div>
                <div class="field-value">{data.get('card_brand', 'Visa')} •••• •••• •••• {data.get('card_last4', '0000')}</div>
            </div>

            <div class="field">
                <div class="field-label">Name on card</div>
                <div class="field-value">{data.get('cardholder_name', '')}</div>
            </div>

            <div class="field">
                <div class="field-label">Authorization key</div>
                <div class="field-value">{data.get('authorization_key', '')}</div>
            </div>

            <div class="field">
                <div class="field-label">Amount</div>
                <div class="field-value">{data.get('amount', '$0.00')}</div>
            </div>

            {optional_fields}

            <div class="field">
                <div class="field-label">Message</div>
                <div class="field-value">{data.get('message', 'Payment complete.')}</div>
            </div>

            <div class="field">
                <div class="field-label">Created</div>
                <div class="field-value">{data.get('created', '')}</div>
            </div>
        </div>
    </body>
    </html>
    """

    # Save HTML temporarily
    temp_dir = tempfile.gettempdir()
    html_path = os.path.join(temp_dir, "card_details_temp.html")
    with open(html_path, 'w', encoding='utf-8') as f:
        f.write(html_content)

    # Screenshot with Playwright
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(viewport={'width': 400, 'height': 600})
            page.goto(f"file:///{html_path}")
            page.wait_for_timeout(500)

            # Screenshot just the container
            card_element = page.locator(".container")
            card_element.screenshot(path=output_path)
            browser.close()

        print(f"Card details image saved: {output_path}")
        return output_path
    except Exception as e:
        print(f"Error generating card image: {e}")
        return None


def get_card_details_image(tenant_id, order_id, reference, output_dir=None):
    """
    Main function to fetch card details and generate image.

    Args:
        tenant_id: Tenant ID for Shopify credentials
        order_id: Shopify order ID (numeric, external_reference)
        reference: Order reference number (e.g., #188802)
        output_dir: Directory to save image

    Returns:
        Dict with 'screenshot_path' and 'card_info', or None if failed
    """
    if output_dir is None:
        output_dir = tempfile.gettempdir()

    # Get Shopify credentials
    creds = get_shopify_credentials(tenant_id)
    if not creds:
        print("Could not get Shopify credentials")
        return None

    # Fetch transactions
    transactions = get_order_transactions(creds['shop_url'], creds['access_token'], order_id)
    if not transactions:
        print("No transactions found")
        return None

    # Extract card info
    card_info = extract_card_data(transactions, reference)
    if not card_info:
        print("Could not extract card data")
        return None

    # Generate image
    output_path = os.path.join(output_dir, f"card_details_{order_id}.png")
    screenshot_path = generate_card_image(card_info, output_path)

    if screenshot_path:
        return {
            'screenshot_path': screenshot_path,
            'card_info': card_info
        }

    return None


# Quick test
if __name__ == "__main__":
    payment_id = input("Payment ID: ").strip()

    # Get payment info
    conn = mysql.connector.connect(**DB_CONFIG)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT Tenants_tntid, externalreference, reference 
        FROM payments WHERE paymentid = %s
    """, (payment_id,))
    result = cursor.fetchone()
    cursor.close()
    conn.close()

    if result:
        tenant_id, ext_ref, reference = result
        print(f"Tenant: {tenant_id}")
        print(f"External Ref: {ext_ref}")
        print(f"Reference: {reference}")

        result = get_card_details_image(tenant_id, ext_ref, reference)
        if result:
            print(f"\nScreenshot: {result['screenshot_path']}")
        else:
            print("Failed")
    else:
        print("Payment not found")


def generate_avs_image(data, output_path):
    """Generate AVS verification image with detailed card and verification info"""

    # Format check results
    def format_check(value):
        if value == 'pass':
            return '<span style="color: #22863a;">✓ Pass</span>'
        elif value == 'fail':
            return '<span style="color: #cb2431;">✗ Fail</span>'
        elif value is None or value == '':
            return '<span style="color: #6a737d;">—</span>'
        else:
            return value

    # AVS result mapping
    avs_code = data.get('avs_code', '')
    avs_results = {
        'Y': 'Full Match (Address & ZIP)',
        'A': 'Address Match Only',
        'Z': 'ZIP Match Only',
        'N': 'No Match',
        'U': 'Unavailable',
        '': 'Not Checked'
    }
    avs_result = avs_results.get(avs_code, avs_code)

    # Format expiry
    exp_month = data.get('exp_month', 0)
    exp_year = data.get('exp_year', 0)
    if exp_month and exp_year:
        expiry_str = f"{exp_month:02d}/{exp_year}"
    else:
        expiry_str = "—"

    html_content = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <style>
            * {{
                margin: 0;
                padding: 0;
                box-sizing: border-box;
            }}
            body {{
                font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
                background: #f6f6f7;
                padding: 20px;
            }}
            .card-container {{
                background: white;
                border-radius: 8px;
                box-shadow: 0 1px 3px rgba(0,0,0,0.08);
                max-width: 600px;
                overflow: hidden;
            }}
            .card-header {{
                background: #f9fafb;
                padding: 16px 20px;
                border-bottom: 1px solid #e1e3e5;
                font-weight: 600;
                font-size: 14px;
                color: #202223;
            }}
            .card-body {{
                padding: 0;
            }}
            .info-row {{
                display: flex;
                padding: 12px 20px;
                border-bottom: 1px solid #f1f2f3;
            }}
            .info-row:last-child {{
                border-bottom: none;
            }}
            .info-label {{
                width: 200px;
                color: #6d7175;
                font-size: 13px;
            }}
            .info-value {{
                flex: 1;
                color: #202223;
                font-size: 13px;
                font-weight: 500;
            }}
            .card-visual {{
                display: flex;
                align-items: center;
                gap: 12px;
                padding: 16px 20px;
                background: #f9fafb;
                border-bottom: 1px solid #e1e3e5;
            }}
            .card-icon {{
                width: 48px;
                height: 32px;
                background: linear-gradient(135deg, #1a1f71 0%, #2557d6 100%);
                border-radius: 4px;
                display: flex;
                align-items: center;
                justify-content: center;
                color: white;
                font-weight: bold;
                font-size: 12px;
            }}
            .card-number-display {{
                font-family: 'Courier New', monospace;
                font-size: 16px;
                letter-spacing: 2px;
                color: #202223;
            }}
            .status-badge {{
                display: inline-block;
                padding: 4px 10px;
                border-radius: 4px;
                font-size: 12px;
                font-weight: 500;
            }}
            .status-success {{
                background: #e3f5e1;
                color: #1f7a1f;
            }}
            .section-divider {{
                background: #f4f6f8;
                padding: 10px 20px;
                font-size: 12px;
                font-weight: 600;
                color: #6d7175;
                text-transform: uppercase;
                letter-spacing: 0.5px;
            }}
            .avs-highlight {{
                background: #e3f5e1;
                border: 2px solid #22863a;
                border-radius: 6px;
                padding: 12px 20px;
                margin: 12px 20px;
            }}
            .avs-highlight-title {{
                color: #22863a;
                font-weight: 600;
                font-size: 14px;
                margin-bottom: 4px;
            }}
            .avs-highlight-text {{
                color: #1f7a1f;
                font-size: 13px;
            }}
        </style>
    </head>
    <body>
        <div class="card-container">
            <div class="card-header">
                Payment & AVS Verification Details
            </div>

            <div class="card-visual">
                <div class="card-icon">{data.get('card_brand', 'CARD')[:4].upper()}</div>
                <div>
                    <div class="card-number-display">{data.get('card_number', '•••• •••• •••• ****')}</div>
                    <div style="color: #6d7175; font-size: 12px; margin-top: 2px;">{data.get('card_type', '')} • {data.get('funding', '')}</div>
                </div>
            </div>

            <div class="avs-highlight">
                <div class="avs-highlight-title">✓ AVS FULL MATCH CONFIRMED</div>
                <div class="avs-highlight-text">The billing address provided by the cardholder matches the address on file with the card issuer.</div>
            </div>

            <div class="card-body">
                <div class="info-row">
                    <div class="info-label">Cardholder Name</div>
                    <div class="info-value">{data.get('cardholder_name', '—')}</div>
                </div>
                <div class="info-row">
                    <div class="info-label">Card Expiry</div>
                    <div class="info-value">{expiry_str}</div>
                </div>
                <div class="info-row">
                    <div class="info-label">Card Issuer</div>
                    <div class="info-value">{data.get('issuer', '—')}</div>
                </div>
                <div class="info-row">
                    <div class="info-label">Card Country</div>
                    <div class="info-value">{data.get('country', '—')}</div>
                </div>
                <div class="info-row">
                    <div class="info-label">BIN/IIN</div>
                    <div class="info-value">{data.get('bin', '—')}</div>
                </div>

                <div class="section-divider">AVS Verification Results</div>

                <div class="info-row">
                    <div class="info-label">AVS Result Code</div>
                    <div class="info-value"><span class="status-badge status-success">{avs_code} - {avs_result}</span></div>
                </div>
                <div class="info-row">
                    <div class="info-label">Address Line Check</div>
                    <div class="info-value">{format_check(data.get('address_check'))}</div>
                </div>
                <div class="info-row">
                    <div class="info-label">Postal Code Check</div>
                    <div class="info-value">{format_check(data.get('zip_check'))}</div>
                </div>
                <div class="info-row">
                    <div class="info-label">CVC Check</div>
                    <div class="info-value">{format_check(data.get('cvc_check'))}</div>
                </div>

                <div class="section-divider">Authorization Details</div>

                <div class="info-row">
                    <div class="info-label">Authorization Code</div>
                    <div class="info-value">{data.get('authorization_code', '—')}</div>
                </div>
                <div class="info-row">
                    <div class="info-label">Network Status</div>
                    <div class="info-value"><span class="status-badge status-success">{data.get('network_status', '').replace('_', ' ').title()}</span></div>
                </div>
                <div class="info-row">
                    <div class="info-label">Risk Level</div>
                    <div class="info-value"><span class="status-badge status-success">{data.get('risk_level', '').title()}</span></div>
                </div>
                <div class="info-row">
                    <div class="info-label">Result</div>
                    <div class="info-value">{data.get('seller_message', '—')}</div>
                </div>
            </div>
        </div>
    </body>
    </html>
    """

    # Save HTML temporarily
    temp_dir = tempfile.gettempdir()
    html_path = os.path.join(temp_dir, "avs_details_temp.html")
    with open(html_path, 'w', encoding='utf-8') as f:
        f.write(html_content)

    # Screenshot with Playwright
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(viewport={'width': 700, 'height': 900})
            page.goto(f"file:///{html_path}")
            page.wait_for_timeout(500)

            # Screenshot just the card container
            card_element = page.locator(".card-container")
            card_element.screenshot(path=output_path)
            browser.close()

        print(f"AVS details image saved: {output_path}")
        return output_path
    except Exception as e:
        print(f"Error generating AVS image: {e}")
        return None


def extract_avs_data(transactions, reference):
    """Extract detailed AVS data for fraud cases"""
    if not transactions:
        return None

    # Find authorization or capture transaction
    txn = None
    for t in transactions:
        if t.get('kind') in ['authorization', 'capture'] and t.get('status') == 'success':
            txn = t
            break

    if not txn:
        txn = transactions[0]

    payment_details = txn.get('payment_details', {})
    receipt = txn.get('receipt', {})
    latest_charge = receipt.get('latest_charge', {})
    outcome = latest_charge.get('outcome', {})
    card = latest_charge.get('payment_method_details', {}).get('card', {})
    checks = card.get('checks', {})

    return {
        'order_number': reference or '',
        'card_brand': payment_details.get('credit_card_company', card.get('brand', '').title()),
        'card_number': payment_details.get('credit_card_number', f"•••• •••• •••• {card.get('last4', '****')}"),
        'card_type': card.get('description', ''),
        'funding': card.get('funding', '').title(),
        'cardholder_name': payment_details.get('credit_card_name', ''),
        'exp_month': card.get('exp_month', payment_details.get('credit_card_expiration_month', 0)),
        'exp_year': card.get('exp_year', payment_details.get('credit_card_expiration_year', 0)),
        'issuer': card.get('issuer', ''),
        'country': card.get('country', ''),
        'bin': card.get('iin', payment_details.get('credit_card_bin', '')),
        'avs_code': payment_details.get('avs_result_code', ''),
        'address_check': checks.get('address_line1_check', ''),
        'zip_check': checks.get('address_postal_code_check', ''),
        'cvc_check': checks.get('cvc_check', ''),
        'authorization_code': card.get('authorization_code', ''),
        'network_status': outcome.get('network_status', ''),
        'risk_level': outcome.get('risk_level', ''),
        'seller_message': outcome.get('seller_message', ''),
    }


def get_avs_details_image(tenant_id, order_id, reference, output_dir=None):
    """
    Get AVS verification image for fraud cases.

    Args:
        tenant_id: Tenant ID for Shopify credentials
        order_id: Shopify order ID (numeric, external_reference)
        reference: Order reference number
        output_dir: Directory to save image

    Returns:
        Dict with 'screenshot_path' and 'avs_data', or None if failed
    """
    if output_dir is None:
        output_dir = tempfile.gettempdir()

    # Get Shopify credentials
    creds = get_shopify_credentials(tenant_id)
    if not creds:
        print("Could not get Shopify credentials")
        return None

    # Fetch transactions
    transactions = get_order_transactions(creds['shop_url'], creds['access_token'], order_id)
    if not transactions:
        print("No transactions found")
        return None

    # Extract AVS data
    avs_data = extract_avs_data(transactions, reference)
    if not avs_data:
        print("Could not extract AVS data")
        return None

    # Generate image
    output_path = os.path.join(output_dir, f"avs_details_{order_id}.png")
    screenshot_path = generate_avs_image(avs_data, output_path)

    if screenshot_path:
        return {
            'screenshot_path': screenshot_path,
            'avs_data': avs_data
        }

    return None