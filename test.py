"""
Test script to debug problematic payment IDs
"""

import mysql.connector
import requests
import json

DB_CONFIG = {
    "host": "fugu-sql-prod-rep.mysql.database.azure.com",
    "user": "geckoboard",
    "password": "UrxP3FmJ+z1bF1Xjs<*%",
    "database": "fuguprod",
}

# Problematic IDs
PROBLEM_IDS = [
    "06ce489a-b65b-4839-a35c-af975ebf1561",
    "98a036a6-f47a-4adc-8781-548259292c4d",
    "bb6e53fd-35e0-4625-af40-e321f3355028",
]


def get_shopify_credentials(tenant_id):
    """Get Shopify API credentials from database"""
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


def get_payment_info(payment_id):
    """Get payment info from database"""
    conn = mysql.connector.connect(**DB_CONFIG)
    cursor = conn.cursor()

    query = """
        SELECT Tenants_tntid, externalreference, reference 
        FROM payments WHERE paymentid = %s
    """
    cursor.execute(query, (payment_id,))
    result = cursor.fetchone()
    cursor.close()
    conn.close()

    if result:
        return {
            'tenant_id': result[0],
            'external_reference': result[1],
            'reference': result[2]
        }
    return None


def get_order_transactions(shop_url, access_token, order_id):
    """Fetch transactions for an order from Shopify API"""
    url = f"https://{shop_url}/admin/api/2024-01/orders/{order_id}/transactions.json"

    headers = {
        "X-Shopify-Access-Token": access_token,
        "Content-Type": "application/json"
    }

    response = requests.get(url, headers=headers, timeout=30)

    print(f"  Status: {response.status_code}")

    return response.json()


def test_payment(payment_id):
    print(f"\n{'=' * 60}")
    print(f"Testing: {payment_id}")
    print('=' * 60)

    # Get payment info
    payment_info = get_payment_info(payment_id)
    if not payment_info:
        print("  ERROR: Payment not found in database")
        return

    print(f"  Tenant ID: {payment_info['tenant_id']}")
    print(f"  External Ref: {payment_info['external_reference']}")
    print(f"  Reference: {payment_info['reference']}")

    # Get Shopify credentials
    creds = get_shopify_credentials(payment_info['tenant_id'])
    if not creds:
        print("  ERROR: No Shopify credentials found")
        return

    print(f"  Shop: {creds['shop_url']}")

    # Get transactions
    print(f"\n  Fetching transactions...")
    transactions_response = get_order_transactions(
        creds['shop_url'],
        creds['access_token'],
        payment_info['external_reference']
    )

    # Print full response
    print(f"\n  FULL RESPONSE:")
    print(json.dumps(transactions_response, indent=2))

    # Check structure
    if 'transactions' in transactions_response:
        transactions = transactions_response['transactions']
        print(f"\n  Found {len(transactions)} transactions")

        for i, txn in enumerate(transactions):
            print(f"\n  Transaction {i + 1}:")
            print(f"    Type: {type(txn)}")
            if isinstance(txn, dict):
                print(f"    Kind: {txn.get('kind')}")
                print(f"    Status: {txn.get('status')}")
                print(f"    Amount: {txn.get('amount')}")

                payment_details = txn.get('payment_details')
                print(f"    payment_details type: {type(payment_details)}")
                if isinstance(payment_details, dict):
                    print(f"    payment_details: {json.dumps(payment_details, indent=6)}")
                else:
                    print(f"    payment_details: {payment_details}")

                receipt = txn.get('receipt')
                print(f"    receipt type: {type(receipt)}")
                if isinstance(receipt, str) and len(receipt) > 200:
                    print(f"    receipt: {receipt[:200]}...")
                else:
                    print(f"    receipt: {receipt}")
            else:
                print(f"    RAW: {txn}")
    else:
        print(f"  No 'transactions' key in response")
        print(f"  Keys: {transactions_response.keys()}")


if __name__ == "__main__":
    for pid in PROBLEM_IDS:
        test_payment(pid)