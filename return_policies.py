"""
RETURN POLICIES PER TENANT
Add new tenants here. The key should match the tenant name passed to the script.
"""

RETURN_POLICIES = {

    "edhardyoriginals": {
        "text": "In order to receive a credit the cardholder must initiate the return and send purchased item back to the merchant. Once the merchant receives the item back, the credit will be processed. In this case the merchant has never received both return request and item, so the cardholder is not eligible for a credit.",
        "url": "https://edhardyoriginals.com/pages/returns-exchanges",
        "extract": "Items must be returned within 30 days of purchase. All items must be unworn, unwashed, and with original tags attached. Refunds will be processed within 5-7 business days after we receive your return."
    },

    "e420": {
        "text": "In order to receive a credit the cardholder must initiate the return and send purchased item back to the merchant. Once the merchant receives the item back, the credit will be processed. In this case the merchant has never received both return request and item, so the cardholder is not eligible for a credit.",
        "url": "https://everythingfor420.com/pages/shipping-returns",
        "extract": "Items must be returned within 30 days of purchase. All items must be UNUSED. Once shipped back, customer must contact merchant with your return inquiry."
    },

    "tenant2": {
        "text": "Customer must contact support to initiate a return within 14 days of delivery. Items must be unused and in original packaging. No return request was received from this customer.",
        "url": "https://tenant2.com/return-policy",
        "extract": "All returns must be authorized. Unauthorized returns will not be processed."
    },

    # ========================================
    # ADD MORE TENANTS BELOW
    # ========================================

    # "new_tenant": {
    #     "text": "Main policy text explaining return process and that customer didn't follow it",
    #     "url": "https://example.com/return-policy",
    #     "extract": "Quoted text from the actual policy page"
    # },

    # ========================================
    # DEFAULT FALLBACK (don't remove)
    # ========================================
    "default": {
        "text": "Per merchant's Returns & Exchanges Policy, customers must initiate a return request and send the item back to receive credit. The merchant has never received a return request nor the item back from this customer. The cardholder is therefore not eligible for a credit through chargeback.",
        "url": None,
        "extract": None
    }
}


def get_return_policy(tenant_name):
    """Get return policy for tenant, fallback to default"""
    tenant_key = tenant_name.lower().strip() if tenant_name else "default"
    return RETURN_POLICIES.get(tenant_key, RETURN_POLICIES["default"])