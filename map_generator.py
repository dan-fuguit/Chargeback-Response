"""
MAP GENERATOR
map_generator.py

Generates map images showing IP location, billing address, and shipping address
for location verification in chargeback disputes.
"""

import os
import json
import mysql.connector
from playwright.sync_api import sync_playwright
import math
import tempfile

# Database config
DB_CONFIG = {
    "host": "fugu-sql-prod-rep.mysql.database.azure.com",
    "user": "geckoboard",
    "password": "UrxP3FmJ+z1bF1Xjs<*%",
    "database": "fuguprod",
}


def get_location_data(paymentid):
    """
    Get IP, billing, and shipping location coordinates from database.

    Args:
        paymentid: Payment ID to lookup

    Returns:
        Dict with ip, billing, shipping locations (each with lat, lng, etc.)
    """
    try:
        conn = mysql.connector.connect(**DB_CONFIG)
        cursor = conn.cursor()

        query = """
            SELECT ipcache.data, p.billing_address, pb.address
            FROM payments p
            JOIN ipcache ON ipcache.ip = p.ip
            LEFT JOIN paymentbeneficiaries pb ON p.paymentid = pb.payments_paymentid
            WHERE paymentid = %s
        """
        cursor.execute(query, (paymentid,))
        result = cursor.fetchone()
        cursor.close()
        conn.close()

        if not result:
            print(f"No location data found for payment {paymentid}")
            return None

        ip_data_raw, billing_data_raw, shipping_data_raw = result

        # Parse data
        ip_data = json.loads(ip_data_raw) if isinstance(ip_data_raw, str) else ip_data_raw
        billing_data = json.loads(billing_data_raw) if isinstance(billing_data_raw, str) else billing_data_raw
        shipping_data = json.loads(shipping_data_raw) if isinstance(shipping_data_raw,
                                                                    str) else shipping_data_raw if shipping_data_raw else None

        locations = {}

        # IP Location
        if ip_data and ip_data.get('latitude') and ip_data.get('longitude'):
            locations['ip'] = {
                'lat': ip_data['latitude'],
                'lng': ip_data['longitude'],
                'label': 'IP Location',
                'city': ip_data.get('city', ''),
                'region': ip_data.get('region', ''),
                'country': ip_data.get('country_name', ''),
                'color': '#e53e3e'  # Red
            }

        # Billing Location
        if billing_data and billing_data.get('latitude') and billing_data.get('longitude'):
            locations['billing'] = {
                'lat': billing_data['latitude'],
                'lng': billing_data['longitude'],
                'label': 'Billing Address',
                'address': billing_data.get('address1', ''),
                'city': billing_data.get('city', ''),
                'region': billing_data.get('province', ''),
                'country': billing_data.get('country', ''),
                'color': '#3182ce'  # Blue
            }

        # Shipping Location
        if shipping_data and shipping_data.get('latitude') and shipping_data.get('longitude'):
            locations['shipping'] = {
                'lat': shipping_data['latitude'],
                'lng': shipping_data['longitude'],
                'label': 'Shipping Address',
                'address': shipping_data.get('address1', ''),
                'city': shipping_data.get('city', ''),
                'region': shipping_data.get('province', ''),
                'country': shipping_data.get('country', ''),
                'color': '#38a169'  # Green
            }

        return locations

    except Exception as e:
        print(f"Error getting location data: {e}")
        return None


def calculate_distance(lat1, lng1, lat2, lng2):
    """Calculate distance between two points in miles using Haversine formula"""
    R = 3959  # Earth's radius in miles

    lat1_rad = math.radians(lat1)
    lat2_rad = math.radians(lat2)
    delta_lat = math.radians(lat2 - lat1)
    delta_lng = math.radians(lng2 - lng1)

    a = math.sin(delta_lat / 2) ** 2 + math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(delta_lng / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

    return R * c


def analyze_locations(locations, max_relevant_distance=100):
    """
    Analyze locations and determine which are relevant (close to each other).

    Args:
        locations: Dict with ip, billing, shipping locations
        max_relevant_distance: Max distance in miles to consider "close"

    Returns:
        Dict with distances, relevant_locations list, and summary text
    """
    analysis = {
        'distances': {},
        'relevant_locations': [],
        'all_close': False,
        'summary': '',
        'summary_text': ''
    }

    if not locations:
        return analysis

    location_keys = list(locations.keys())

    # Calculate all pairwise distances
    for i, key1 in enumerate(location_keys):
        for key2 in location_keys[i + 1:]:
            loc1 = locations[key1]
            loc2 = locations[key2]
            dist = calculate_distance(loc1['lat'], loc1['lng'], loc2['lat'], loc2['lng'])
            pair_key = f"{key1}_to_{key2}"
            analysis['distances'][pair_key] = round(dist, 2)

    # Determine relevant locations - IP is always the anchor
    if 'ip' in locations:
        analysis['relevant_locations'].append('ip')

    # Check if billing is close to IP
    if 'ip' in locations and 'billing' in locations:
        dist = analysis['distances'].get('ip_to_billing', float('inf'))
        if dist <= max_relevant_distance:
            if 'billing' not in analysis['relevant_locations']:
                analysis['relevant_locations'].append('billing')

    # Check if shipping is close to IP or billing
    if 'shipping' in locations:
        close_to_ip = False
        close_to_billing = False

        if 'ip' in locations:
            dist = analysis['distances'].get('ip_to_shipping', float('inf'))
            close_to_ip = dist <= max_relevant_distance

        if 'billing' in locations:
            dist = analysis['distances'].get('billing_to_shipping', float('inf'))
            close_to_billing = dist <= max_relevant_distance

        if close_to_ip or close_to_billing:
            analysis['relevant_locations'].append('shipping')

    # Check if all locations are close
    all_distances = list(analysis['distances'].values())
    if all_distances and max(all_distances) <= max_relevant_distance:
        analysis['all_close'] = True

    # Build summary for map display
    summaries = []
    if 'ip_to_billing' in analysis['distances']:
        dist = analysis['distances']['ip_to_billing']
        summaries.append(f"IP to Billing: {dist:.1f} miles")
    if 'ip_to_shipping' in analysis['distances']:
        dist = analysis['distances']['ip_to_shipping']
        summaries.append(f"IP to Shipping: {dist:.1f} miles")
    if 'billing_to_shipping' in analysis['distances']:
        dist = analysis['distances']['billing_to_shipping']
        summaries.append(f"Billing to Shipping: {dist:.1f} miles")

    analysis['summary'] = " | ".join(summaries)

    # Build text summary for PDF
    text_parts = []
    if 'ip_to_billing' in analysis['distances']:
        dist = analysis['distances']['ip_to_billing']
        text_parts.append(
            f"The transaction IP address is located approximately {dist:.1f} miles from the billing address")
    if 'ip_to_shipping' in analysis['distances']:
        dist = analysis['distances']['ip_to_shipping']
        text_parts.append(f"{dist:.1f} miles from the shipping address")
    if 'billing_to_shipping' in analysis['distances']:
        dist = analysis['distances']['billing_to_shipping']
        if dist < 1:
            text_parts.append("Billing and shipping addresses are at the same location")
        else:
            text_parts.append(f"Billing and shipping addresses are {dist:.1f} miles apart")

    analysis['summary_text'] = ". ".join(text_parts) + "." if text_parts else ""

    return analysis


def generate_location_map(paymentid, output_dir=None):
    """
    Generate a map image showing IP, billing, and shipping locations.

    Args:
        paymentid: Payment ID to lookup
        output_dir: Directory to save the map image

    Returns:
        Dict with:
            - screenshot_path: Path to map image
            - analysis: Location analysis with distances
            - locations: Raw location data
        Or None if failed
    """
    if output_dir is None:
        output_dir = tempfile.gettempdir()

    # Get location data
    locations = get_location_data(paymentid)
    if not locations:
        print("No location data available")
        return None

    # Analyze locations
    analysis = analyze_locations(locations, max_relevant_distance=100)

    if len(analysis['relevant_locations']) < 2:
        print("Not enough relevant locations to generate map")
        return {
            'screenshot_path': None,
            'analysis': analysis,
            'locations': locations
        }

    # Generate map
    output_path = os.path.join(output_dir, f"location_map_{paymentid[:8]}.png")

    # Filter to only relevant locations
    relevant_locs = {k: v for k, v in locations.items() if k in analysis['relevant_locations']}

    # Calculate center point
    lats = [loc['lat'] for loc in relevant_locs.values()]
    lngs = [loc['lng'] for loc in relevant_locs.values()]
    center_lat = sum(lats) / len(lats)
    center_lng = sum(lngs) / len(lngs)

    # Build markers JavaScript with offsets to avoid overlap
    markers_js = ""
    coords_for_bounds = []

    marker_offsets = {
        'ip': [0, 0],
        'billing': [0, -45],
        'shipping': [0, -90]
    }

    for key, loc in relevant_locs.items():
        coords_for_bounds.append(f"[{loc['lat']}, {loc['lng']}]")
        offset = marker_offsets.get(key, [0, 0])
        markers_js += f"""
            var {key}Icon = L.divIcon({{
                className: 'custom-marker',
                html: '<div style="background-color: {loc['color']}; color: black; padding: 5px 10px; border-radius: 5px; font-weight: bold; white-space: nowrap; box-shadow: 0 2px 5px rgba(0,0,0,0.3); border: 1px solid rgba(0,0,0,0.2);">{loc['label']}</div>',
                iconAnchor: [{50 + offset[0]}, {40 + offset[1]}]
            }});
            L.marker([{loc['lat']}, {loc['lng']}], {{icon: {key}Icon, zIndexOffset: {1000 if key == 'ip' else 500 if key == 'billing' else 0}}}).addTo(map);
        """

    # Build lines between all relevant points
    lines_js = ""
    keys = list(relevant_locs.keys())
    for i, key1 in enumerate(keys):
        for key2 in keys[i + 1:]:
            loc1 = relevant_locs[key1]
            loc2 = relevant_locs[key2]
            lines_js += f"""
            L.polyline([
                [{loc1['lat']}, {loc1['lng']}],
                [{loc2['lat']}, {loc2['lng']}]
            ], {{color: '#718096', weight: 2, dashArray: '5, 10'}}).addTo(map);
            """

    # Distance label in corner
    distance_text = analysis['summary'].replace(' | ', '<br>')

    html_content = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
        <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
        <style>
            body {{ margin: 0; padding: 0; }}
            #map {{ width: 800px; height: 500px; }}
            .distance-box {{
                position: absolute;
                bottom: 20px;
                right: 20px;
                background: white;
                padding: 10px 15px;
                border-radius: 5px;
                box-shadow: 0 2px 10px rgba(0,0,0,0.2);
                font-family: Arial, sans-serif;
                font-size: 12px;
                z-index: 1000;
                line-height: 1.6;
            }}
            .distance-box b {{
                font-size: 13px;
            }}
        </style>
    </head>
    <body>
        <div id="map"></div>
        <div class="distance-box">
            <b>Distances:</b><br>
            {distance_text}
        </div>
        <script>
            var map = L.map('map').setView([{center_lat}, {center_lng}], 10);

            L.tileLayer('https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png', {{
                attribution: '© OpenStreetMap'
            }}).addTo(map);

            {markers_js}
            {lines_js}

            // Fit bounds to show all markers
            var bounds = L.latLngBounds([{', '.join(coords_for_bounds)}]);
            map.fitBounds(bounds, {{padding: [60, 60]}});
        </script>
    </body>
    </html>
    """

    # Save HTML temporarily
    temp_dir = tempfile.gettempdir()
    html_path = os.path.join(temp_dir, "map_temp.html")
    with open(html_path, 'w') as f:
        f.write(html_content)

    # Screenshot with Playwright
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(viewport={'width': 800, 'height': 500})
            page.goto(f"file:///{html_path}")
            page.wait_for_timeout(2000)
            page.screenshot(path=output_path)
            browser.close()

        print(f"Location map saved: {output_path}")

        return {
            'screenshot_path': output_path,
            'analysis': analysis,
            'locations': locations
        }

    except Exception as e:
        print(f"Error generating map: {e}")
        return {
            'screenshot_path': None,
            'analysis': analysis,
            'locations': locations
        }


# Quick test
if __name__ == "__main__":
    payment_id = input("Payment ID: ").strip()
    result = generate_location_map(payment_id)

    if result:
        print(f"\nMap: {result['screenshot_path']}")
        print(f"Summary: {result['analysis']['summary_text']}")
        print(f"Distances: {result['analysis']['distances']}")