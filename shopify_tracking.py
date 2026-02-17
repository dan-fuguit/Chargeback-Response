import os
import time
import random
import requests
import mysql.connector
from mysql.connector import Error
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

DB_HOST = "fugu-sql-prod-rep.mysql.database.azure.com"
DB_USER = "geckoboard"
DB_PASSWORD = "UrxP3FmJ+z1bF1Xjs<*%"
DB_NAME = "fuguprod"


# =========================
# COOKIE HANDLER
# =========================
def accept_cookies(page):
    selectors = [
        'button:has-text("Accept all cookies")',
        'button:has-text("Accept All Cookies")',
        'button:has-text("Accept All")',
        '#truste-consent-button',
        '[id*="cookie"] button',
    ]

    for sel in selectors:
        try:
            btn = page.locator(sel).first
            if btn.is_visible(timeout=1200):
                btn.click()
                page.wait_for_timeout(800)
                print("🍪 Cookies accepted")
                return
        except:
            pass


# =========================
# MAIN CLASS
# =========================
class ShopifyTrackingCapture:
    def __init__(self):
        self.db_config = {
            "host": DB_HOST,
            "database": DB_NAME,
            "user": DB_USER,
            "password": DB_PASSWORD,
        }
        self.conn = None

    # ---------- DB ----------
    def _connect_db(self):
        if not self.conn or not self.conn.is_connected():
            self.conn = mysql.connector.connect(**self.db_config)
        return self.conn

    def get_shopify_credentials_by_id(self, tenant_id):
        try:
            cur = self._connect_db().cursor(dictionary=True)
            cur.execute(
                """
                SELECT shopname, accesstoken
                FROM shopifyintegration
                WHERE tenantid = %s
                LIMIT 1
                """,
                (tenant_id,),
            )
            row = cur.fetchone()
            cur.close()
            return row
        except Error:
            return None

    # ---------- SHOPIFY ----------
    def get_tracking_info(self, shop_url, token, reference):
        reference = str(reference).replace("#", "")
        if not shop_url.endswith(".myshopify.com"):
            shop_url += ".myshopify.com"

        headers = {"X-Shopify-Access-Token": token}

        for ref in (reference, f"#{reference}"):
            r = requests.get(
                f"https://{shop_url}/admin/api/2024-01/orders.json",
                headers=headers,
                params={"name": ref, "status": "any"},
                timeout=30,
            )
            if r.status_code == 200:
                orders = r.json().get("orders", [])
                if orders:
                    break
        else:
            return None

        for f in orders[0].get("fulfillments", []):
            if f.get("tracking_number"):
                # Use Shopify's tracking_url if available, otherwise build our own
                tracking_url = f.get("tracking_url")
                if not tracking_url:
                    tracking_url = self._build_tracking_url(
                        f["tracking_number"], f.get("tracking_company", "")
                    )

                print(f"Using tracking URL: {tracking_url}")

                return {
                    "tracking_number": f["tracking_number"],
                    "tracking_company": f.get("tracking_company"),
                    "tracking_url": tracking_url,
                }
        return None

    def _build_tracking_url(self, num, carrier):
        carrier = (carrier or "").lower()
        if "fedex" in carrier:
            return f"https://www.fedex.com/fedextrack/?tracknumbers={num}"
        if "ups" in carrier:
            return f"https://www.ups.com/track?tracknum={num}"
        if "usps" in carrier:
            return f"https://tools.usps.com/go/TrackConfirmAction?tLabels={num}"
        if "dhl" in carrier:
            return f"https://www.dhl.com/us-en/home/tracking.html?tracking-id={num}"
        return None

    # ---------- SCREENSHOT ----------
    def screenshot_tracking_page(self, tracking_url, output_path, attempts=2):
        last_error = None

        for attempt in range(attempts):
            try:
                return self._screenshot_once(tracking_url, output_path)
            except Exception as e:
                print(f"Attempt {attempt + 1} failed: {e}")
                last_error = e
                time.sleep(3)

        raise last_error

    def _screenshot_once(self, tracking_url, output_path):
        with sync_playwright() as p:
            # Connect to existing Chrome running with --remote-debugging-port=9222
            try:
                browser = p.chromium.connect_over_cdp("http://127.0.0.1:9222")
                print("Connected to existing Chrome")
            except Exception as e:
                print(f"Could not connect to Chrome on port 9222: {e}")
                print("Make sure Chrome is running with: chrome.exe --remote-debugging-port=9222")
                raise

            # Get the default context (your real Chrome session)
            context = browser.contexts[0]
            page = context.new_page()

            print(f"Loading: {tracking_url}")
            page.goto(tracking_url, wait_until="domcontentloaded", timeout=60000)

            # Wait longer for FedEx to load
            print("Waiting for page to load...")
            page.wait_for_timeout(8000)

            accept_cookies(page)

            page.wait_for_timeout(3000)

            # Detect FedEx block
            page_content = page.content().lower()
            if "unable to retrieve" in page_content or "we are sorry" in page_content:
                page.close()
                raise Exception("FedEx blocked page")

            # Wait for tracking info to appear
            try:
                page.wait_for_selector(
                    "text=Delivered, text=In transit, text=Out for delivery, text=Shipment information",
                    timeout=10000,
                )
                print("Tracking info found!")
            except PlaywrightTimeoutError:
                print("Timeout waiting for tracking info, taking screenshot anyway...")

            page.screenshot(path=output_path)
            print(f"Screenshot saved: {output_path}")

            # Close just the tab, not the browser
            page.close()
            return output_path

    # ---------- PUBLIC ----------
    def capture_tracking(self, tenant_id, reference, output_dir="/tmp"):
        creds = self.get_shopify_credentials_by_id(tenant_id)
        if not creds:
            return None

        info = self.get_tracking_info(
            creds["shopname"], creds["accesstoken"], reference
        )
        if not info or not info["tracking_url"]:
            return None

        path = os.path.join(output_dir, f"tracking_{reference}.png")
        self.screenshot_tracking_page(info["tracking_url"], path)
        info["screenshot_path"] = path
        return info

    def close(self):
        if self.conn and self.conn.is_connected():
            self.conn.close()


# =========================
# ENTRY POINT
# =========================
def get_shipping_proof(tenant_id=None, tenant_name=None, reference=None, output_dir="/tmp"):
    """
    Get shipping proof screenshot.

    Args:
        tenant_id: Tenant ID (required)
        tenant_name: Tenant name (optional, kept for compatibility)
        reference: Order reference number
        output_dir: Where to save screenshot

    Returns:
        dict with screenshot_path and tracking info, or None
    """
    if not tenant_id or not reference:
        return None

    cap = ShopifyTrackingCapture()
    try:
        return cap.capture_tracking(tenant_id, reference, output_dir)
    finally:
        cap.close()