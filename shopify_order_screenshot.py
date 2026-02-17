"""
SHOPIFY ORDER SCREENSHOT MODULE
shopify_order_screenshot.py

Takes screenshots of Shopify order pages for chargeback evidence.
Uses persistent browser profile - login once and it remembers forever.
"""

from playwright.sync_api import sync_playwright
import os

# Path to persistent browser profile - login saved here
# Uses environment variable if set (for Docker), otherwise default to home directory
BROWSER_PROFILE_DIR = os.environ.get(
    "BROWSER_PROFILE_DIR",
    os.path.join(os.path.expanduser("~"), ".shopify_browser_profile")
)


def do_scroll(page):
    """Scroll to show order details - the main column should be at the top"""
    print("Scrolling to order content...")

    # Target the main order details column
    selectors_to_try = [
        '[class*="_OrderDetailsMainColumn_"]',
        '[class*="OrderDetailsMainColumn"]',
        'text="Fulfilled"',
        'text="Unfulfilled"',
        's-internal-badge:has-text("Fulfilled")',
        's-internal-badge:has-text("Paid")',
    ]

    for selector in selectors_to_try:
        try:
            element = page.locator(selector).first
            if element.is_visible(timeout=1000):
                element.scroll_into_view_if_needed()
                print(f"  Scrolled to: {selector}")
                page.wait_for_timeout(500)
                return True
        except:
            continue

    # Fallback: no scroll needed if element not found
    print("  No scroll needed or element not found")
    return False


def screenshot_shopify_order(store_url, order_number, output_dir="/tmp"):
    """
    Take a screenshot of a Shopify order page.

    Args:
        store_url: Store URL (e.g., 'my-store' or 'my-store.myshopify.com')
        order_number: Order number/reference (e.g., '1001' or '#1001')
        output_dir: Directory to save screenshot

    Returns:
        Path to screenshot file, or None if failed
    """
    # Clean inputs
    if not store_url.endswith('.myshopify.com'):
        store_url = f"{store_url}.myshopify.com"

    order_number = str(order_number).replace('#', '')

    output_path = os.path.join(output_dir, f"shopify_order_{order_number}.png")

    try:
        with sync_playwright() as p:
            # Use persistent context - saves login state forever
            context = p.chromium.launch_persistent_context(
                BROWSER_PROFILE_DIR,
                headless=False,
                viewport={'width': 1280, 'height': 900}
            )

            page = context.pages[0] if context.pages else context.new_page()

            # Go to orders with search
            url = f"https://{store_url}/admin/orders?query={order_number}"
            print(f"Loading: {url}")
            page.goto(url, wait_until="networkidle", timeout=60000)
            page.wait_for_timeout(2000)

            # Check if logged in - if not, wait for manual login
            if "login" in page.url.lower() or "accounts.shopify" in page.url:
                print("\n" + "="*50)
                print("Please login to Shopify in the browser window.")
                print("Your login will be saved for future runs.")
                print("="*50 + "\n")
                # Wait for user to login and navigate to orders
                page.wait_for_url("**/admin/orders**", timeout=300000)  # 5 min timeout
                page.wait_for_timeout(2000)

            # Click the order
            try:
                order_link = page.locator(f'a:has-text("#{order_number}")').first
                order_link.click()
                page.wait_for_timeout(3000)
                print(f"Opened order #{order_number}")
            except:
                print("Could not find exact order, clicking first result...")
                try:
                    page.locator('table tbody tr').first.click()
                    page.wait_for_timeout(3000)
                except:
                    print(f"ERROR: Order {order_number} not found")
                    context.close()
                    return None

            # Scroll to order content
            do_scroll(page)
            page.wait_for_timeout(1000)

            # Take screenshot
            page.screenshot(path=output_path, full_page=False)
            print(f"Screenshot saved: {output_path}")

            context.close()
            return output_path

    except Exception as e:
        print(f"Shopify screenshot error: {e}")
        return None


def get_order_proof(store_url, order_number, output_dir="/tmp"):
    """
    Convenience function for chargeback generators.
    Same as screenshot_shopify_order but with simpler name.

    Returns:
        dict with 'screenshot_path' key, or None if failed
    """
    screenshot_path = screenshot_shopify_order(store_url, order_number, output_dir)

    if screenshot_path:
        return {
            "screenshot_path": screenshot_path,
            "store_url": store_url,
            "order_number": order_number
        }
    return None


def screenshot_shopify_order_by_url(external_reference, order_number, output_dir="/tmp"):
    """
    Take a screenshot of a Shopify order page using direct URL.

    Args:
        external_reference: Direct Shopify admin URL (e.g., https://admin.shopify.com/store/xxx/orders/123)
        order_number: Order number for filename
        output_dir: Directory to save screenshot

    Returns:
        Path to screenshot file, or None if failed
    """
    if not external_reference:
        print("No external_reference URL provided")
        return None

    order_number = str(order_number).replace('#', '')
    output_path = os.path.join(output_dir, f"shopify_order_{order_number}.png")

    try:
        with sync_playwright() as p:
            # Use persistent context - saves login state forever
            context = p.chromium.launch_persistent_context(
                BROWSER_PROFILE_DIR,
                headless=False,
                viewport={'width': 1280, 'height': 900}
            )

            page = context.pages[0] if context.pages else context.new_page()

            # Go directly to the order URL
            print(f"Loading: {external_reference}")
            page.goto(external_reference, wait_until="networkidle", timeout=60000)
            page.wait_for_timeout(3000)

            # Check if logged in - if not, wait for manual login
            if "login" in page.url.lower() or "accounts.shopify" in page.url:
                print("\n" + "="*50)
                print("Please login to Shopify in the browser window.")
                print("Your login will be saved for future runs.")
                print("="*50 + "\n")
                # Wait for user to login
                page.wait_for_url("**/admin/**", timeout=300000)  # 5 min timeout
                # Re-navigate to the order after login
                page.goto(external_reference, wait_until="networkidle", timeout=60000)
                page.wait_for_timeout(3000)

            # Scroll to order content
            do_scroll(page)
            page.wait_for_timeout(1000)

            # Take screenshot
            page.screenshot(path=output_path, full_page=False)
            print(f"Screenshot saved: {output_path}")

            context.close()
            return output_path

    except Exception as e:
        print(f"Shopify screenshot error: {e}")
        return None


# Quick test
if __name__ == "__main__":
    store = input("Store URL: ").strip()
    order = input("Order number: ").strip()

    result = screenshot_shopify_order(store, order, output_dir=".")
    if result:
        print(f"\nSuccess! Screenshot: {result}")
    else:
        print("\nFailed to capture screenshot")