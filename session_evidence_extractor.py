"""
Session Evidence Extractor for Chargeback Response Automation
Extracts and summarizes session data from MySQL for use in chargeback dispute PDFs

Uses new session_evidences table with join:
    payments p
    JOIN paymentsessionevidence pse ON p.externalreference = pse.paymentId
    JOIN session_evidences se ON se.user_id = pse.userid
"""

import mysql.connector
from datetime import datetime
from typing import Dict, List, Optional, Any
import json

# Database credentials
DB_HOST = "fugu-sql-prod-rep.mysql.database.azure.com"
DB_USER = "geckoboard"
DB_PASSWORD = "UrxP3FmJ+z1bF1Xjs<*%"
DB_NAME = "fuguprod"


class SessionEvidenceExtractor:
    """Extract session evidence for chargeback responses"""

    def __init__(self, conn=None):
        if conn:
            self.conn = conn
            self.owns_connection = False
        else:
            self.conn = mysql.connector.connect(
                host=DB_HOST,
                user=DB_USER,
                password=DB_PASSWORD,
                database=DB_NAME
            )
            self.owns_connection = True

    def close(self):
        if self.owns_connection and self.conn:
            self.conn.close()

    def get_session_evidence(self, payment_id: str) -> Dict[str, Any]:
        """Main method: Get all session evidence for a payment"""
        payment_info, sessions = self._get_payment_and_sessions(payment_id)

        if not payment_info:
            return {"error": f"Payment {payment_id} not found"}

        ip_data = self._get_ip_data(payment_info)
        evidence = self._build_evidence_summary(payment_info, sessions, ip_data)

        return evidence

    def _get_payment_and_sessions(self, payment_id: str) -> tuple:
        """Get payment info and all sessions in one query"""
        cursor = self.conn.cursor(dictionary=True)

        query = """
            SELECT 
                p.paymentid,
                p.externalreference,
                p.paymentcreated,
                p.payername,
                p.PayerSurname,
                p.Payer_Email,
                p.IP,
                p.paymentamount,
                p.currency,
                p.DeviceSignature,
                p.Billing_Address,
                p.Payer_Mobile,
                se.id as session_id,
                se.user_id,
                se.tenant_id,
                se.device_id,
                se.ip_addresses,
                se.previous_orders,
                se.time_start,
                se.time_end,
                se.duration,
                se.session
            FROM payments p
            LEFT JOIN paymentsessionevidence pse ON p.externalreference = pse.paymentId
            LEFT JOIN session_evidences se ON se.user_id = pse.userid
            WHERE p.paymentid = %s
            ORDER BY se.time_start
        """
        cursor.execute(query, (payment_id,))
        rows = cursor.fetchall()
        cursor.close()

        if not rows:
            return None, []

        # Extract payment info from first row
        first_row = rows[0]
        payment_info = {
            'paymentid': first_row['paymentid'],
            'externalreference': first_row['externalreference'],
            'paymentcreated': first_row['paymentcreated'],
            'payername': first_row['payername'],
            'PayerSurname': first_row['PayerSurname'],
            'Payer_Email': first_row['Payer_Email'],
            'IP': first_row['IP'],
            'paymentamount': first_row['paymentamount'],
            'currency': first_row['currency'],
            'DeviceSignature': first_row['DeviceSignature'],
            'Billing_Address': first_row['Billing_Address'],
            'Payer_Mobile': first_row['Payer_Mobile'],
        }

        # Extract sessions
        sessions = []
        payment_time = payment_info['paymentcreated']
        seen_session_ids = set()

        for row in rows:
            session_id = row.get('session_id')
            if session_id and session_id not in seen_session_ids:
                seen_session_ids.add(session_id)
                session = {
                    'id': session_id,
                    'user_id': row['user_id'],
                    'tenant_id': row['tenant_id'],
                    'device_id': row['device_id'],
                    'ip_addresses': row['ip_addresses'],
                    'previous_orders': row['previous_orders'],
                    'time_start': row['time_start'],
                    'time_end': row['time_end'],
                    'duration': row['duration'],
                    'session': row['session'],
                }
                session['category'] = self._categorize_session(session, payment_time)
                sessions.append(session)

        return payment_info, sessions

    def _categorize_session(self, session: Dict, payment_time: datetime) -> str:
        """Categorize session as before/during/after payment"""
        time_start = session.get('time_start')
        time_end = session.get('time_end')

        if not payment_time:
            return 'unknown'

        if time_end and time_end < payment_time:
            return 'before'
        elif time_start and time_start >= payment_time:
            return 'after'
        elif time_start and time_end and time_start < payment_time and time_end > payment_time:
            return 'during'
        return 'unknown'

    def _get_ip_data(self, payment_info: Dict) -> Optional[Dict]:
        """Get IP geolocation data from ipcache"""
        ip = payment_info.get('IP')
        if not ip:
            return None

        cursor = self.conn.cursor(dictionary=True)
        cursor.execute("SELECT ip, data FROM ipcache WHERE ip = %s", (ip,))
        result = cursor.fetchone()
        cursor.close()

        if result and result.get('data'):
            try:
                return json.loads(result['data']) if isinstance(result['data'], str) else result['data']
            except:
                return None
        return None

    def _build_evidence_summary(self, payment_info: Dict, sessions: List[Dict], ip_data: Optional[Dict]) -> Dict[
        str, Any]:
        """Build the final evidence summary for chargeback response"""
        session_stats = self._calculate_session_stats(sessions)
        location_info = self._format_location_info(payment_info, ip_data)
        device_info = self._extract_device_info(sessions, payment_info)
        timeline = self._build_session_timeline(sessions, payment_info['paymentcreated'])

        evidence = {
            "payment_id": payment_info['paymentid'],
            "payment_date": payment_info['paymentcreated'].strftime("%B %d, %Y at %I:%M %p") if payment_info[
                'paymentcreated'] else None,
            "customer_name": f"{payment_info.get('payername', '')} {payment_info.get('PayerSurname', '')}".strip(),
            "customer_email": payment_info.get('Payer_Email'),
            "customer_phone": payment_info.get('Payer_Mobile'),
            "billing_address": payment_info.get('Billing_Address'),

            "session_evidence": {
                "text": "Please find below the session activity evidence showing the cardholder's browsing behavior on the merchant's website:",
                "summary": self._generate_session_summary_text(session_stats, location_info, device_info),
                "proof_placeholder": "Session Activity Screenshot"
            },

            "location_evidence": {
                "text": "Please find below the IP geolocation data confirming the transaction origin:",
                "summary": self._generate_location_summary_text(location_info),
                "proof_placeholder": "IP Geolocation Screenshot"
            },

            "device_evidence": {
                "text": "Please find below the device fingerprint information from the transaction:",
                "summary": self._generate_device_summary_text(device_info),
                "proof_placeholder": "Device Fingerprint Screenshot"
            },

            "_raw_data": {
                "session_stats": session_stats,
                "location_info": location_info,
                "device_info": device_info,
                "timeline": timeline,
                "total_sessions": len(sessions)
            }
        }

        return evidence

    def _calculate_session_stats(self, sessions: List[Dict]) -> Dict:
        """Calculate session statistics"""
        if not sessions:
            return {
                "total_sessions": 0,
                "sessions_before": 0,
                "sessions_during": 0,
                "sessions_after": 0,
                "avg_duration_before": None,
                "avg_duration_during": None,
                "avg_duration_after": None,
                "total_time_on_site": 0,
                "unique_ips": [],
                "total_clicks": 0,
                "total_moves": 0,
                "has_previous_orders": False
            }

        stats = {
            "total_sessions": len(sessions),
            "sessions_before": 0,
            "sessions_during": 0,
            "sessions_after": 0,
            "durations_before": [],
            "durations_during": [],
            "durations_after": [],
            "unique_ips": set(),
            "total_clicks": 0,
            "total_moves": 0,
            "has_previous_orders": False
        }

        for s in sessions:
            cat = s.get('category', 'unknown')
            duration = s.get('duration', 0) or 0

            if cat == 'before':
                stats['sessions_before'] += 1
                if duration > 0:
                    stats['durations_before'].append(duration)
            elif cat == 'during':
                stats['sessions_during'] += 1
                if duration > 0:
                    stats['durations_during'].append(duration)
            elif cat == 'after':
                stats['sessions_after'] += 1
                if duration > 0:
                    stats['durations_after'].append(duration)

            # Collect IPs from ip_addresses field (JSON array as string)
            ips = s.get('ip_addresses')
            if ips:
                try:
                    if isinstance(ips, str):
                        ip_list = json.loads(ips)
                        stats['unique_ips'].update(ip_list)
                    elif isinstance(ips, list):
                        stats['unique_ips'].update(ips)
                except:
                    pass

            # Parse session JSON for activity stats
            session_data = s.get('session')
            if session_data:
                try:
                    if isinstance(session_data, str):
                        session_data = json.loads(session_data)
                    stats['total_clicks'] += session_data.get('clickCount', 0) or 0
                    stats['total_moves'] += session_data.get('moveCount', 0) or 0
                except:
                    pass

            # Check for previous orders
            prev_orders = s.get('previous_orders')
            if prev_orders:
                try:
                    if isinstance(prev_orders, str):
                        prev_orders = json.loads(prev_orders)
                    if prev_orders and len(prev_orders) > 0:
                        stats['has_previous_orders'] = True
                except:
                    pass

        # Calculate averages
        stats['avg_duration_before'] = round(sum(stats['durations_before']) / len(stats['durations_before']), 1) if \
        stats['durations_before'] else None
        stats['avg_duration_during'] = round(sum(stats['durations_during']) / len(stats['durations_during']), 1) if \
        stats['durations_during'] else None
        stats['avg_duration_after'] = round(sum(stats['durations_after']) / len(stats['durations_after']), 1) if stats[
            'durations_after'] else None
        stats['total_time_on_site'] = sum(stats['durations_before']) + sum(stats['durations_during']) + sum(
            stats['durations_after'])
        stats['unique_ips'] = list(stats['unique_ips'])

        del stats['durations_before']
        del stats['durations_during']
        del stats['durations_after']

        return stats

    def _format_location_info(self, payment_info: Dict, ip_data: Optional[Dict]) -> Dict:
        """Format location information"""
        location = {
            "ip_address": payment_info.get('IP'),
            "country": None,
            "country_code": None,
            "city": None,
            "region": None,
            "postal": None,
            "timezone": None,
            "isp": None,
            "is_proxy": False,
            "coordinates": None
        }

        if ip_data:
            location.update({
                "country": ip_data.get('country_name') or ip_data.get('country'),
                "country_code": ip_data.get('country_code'),
                "city": ip_data.get('city'),
                "region": ip_data.get('region'),
                "postal": ip_data.get('postal'),
                "timezone": ip_data.get('timezone'),
                "isp": ip_data.get('org') or ip_data.get('isp'),
                "is_proxy": ip_data.get('proxyCheck', {}).get('block', False) if isinstance(ip_data.get('proxyCheck'),
                                                                                            dict) else False,
                "coordinates": f"{ip_data.get('latitude')}, {ip_data.get('longitude')}" if ip_data.get(
                    'latitude') else None
            })

        return location

    def _extract_device_info(self, sessions: List[Dict], payment_info: Dict) -> Dict:
        """Extract device/browser information from session JSON"""
        device = {
            "device_signature": payment_info.get('DeviceSignature'),
            "user_agents": [],
            "browsers": set(),
            "operating_systems": set(),
            "is_mobile": False,
            "is_bot": False
        }

        for s in sessions:
            session_data = s.get('session')
            if session_data:
                try:
                    if isinstance(session_data, str):
                        session_data = json.loads(session_data)

                    # Get user agents from session JSON
                    user_agents = session_data.get('userAgents', [])
                    for ua in user_agents:
                        if ua and ua not in device['user_agents']:
                            device['user_agents'].append(ua)
                            self._parse_user_agent(ua, device)

                    # Check if bot
                    if session_data.get('csIsBot', 0) == 1:
                        device['is_bot'] = True

                except:
                    pass

        device['browsers'] = list(device['browsers'])
        device['operating_systems'] = list(device['operating_systems'])

        return device

    def _parse_user_agent(self, ua: str, device: Dict):
        """Parse user agent string to extract browser/OS info"""
        ua_lower = ua.lower()

        # Browser detection
        if 'chrome' in ua_lower and 'edg' not in ua_lower:
            device['browsers'].add('Chrome')
        elif 'firefox' in ua_lower:
            device['browsers'].add('Firefox')
        elif 'safari' in ua_lower and 'chrome' not in ua_lower:
            device['browsers'].add('Safari')
        elif 'edg' in ua_lower:
            device['browsers'].add('Edge')

        # OS detection
        if 'windows' in ua_lower:
            device['operating_systems'].add('Windows')
        elif 'mac os' in ua_lower or 'macintosh' in ua_lower:
            device['operating_systems'].add('macOS')
        elif 'linux' in ua_lower and 'android' not in ua_lower:
            device['operating_systems'].add('Linux')

        if 'android' in ua_lower:
            device['operating_systems'].add('Android')
            device['is_mobile'] = True
        elif 'iphone' in ua_lower or 'ipad' in ua_lower:
            device['operating_systems'].add('iOS')
            device['is_mobile'] = True

    def _build_session_timeline(self, sessions: List[Dict], payment_time: datetime) -> List[Dict]:
        """Build a timeline of session activity"""
        timeline = []

        for s in sessions:
            entry = {
                "time_start": s['time_start'].isoformat() if s.get('time_start') else None,
                "time_end": s['time_end'].isoformat() if s.get('time_end') else None,
                "duration_seconds": s.get('duration'),
                "category": s.get('category'),
                "ip": s.get('ip_addresses')
            }
            timeline.append(entry)

        timeline.sort(key=lambda x: x['time_start'] or '')
        return timeline

    def _format_duration(self, seconds: float) -> str:
        """Format seconds into readable duration"""
        if not seconds:
            return "N/A"
        if seconds < 60:
            return f"{int(seconds)} seconds"
        elif seconds < 3600:
            mins = int(seconds / 60)
            secs = int(seconds % 60)
            return f"{mins} min {secs} sec"
        else:
            hours = int(seconds / 3600)
            mins = int((seconds % 3600) / 60)
            return f"{hours}h {mins}m"

    def _generate_session_summary_text(self, stats: Dict, location: Dict, device: Dict) -> str:
        """Generate human-readable session summary for PDF"""
        lines = []

        if stats['total_sessions'] > 0:
            lines.append(f"The customer had {stats['total_sessions']} browsing session(s) on the merchant's website.")

            if stats['sessions_before'] > 0:
                dur = self._format_duration(stats['avg_duration_before']) if stats['avg_duration_before'] else "N/A"
                lines.append(f"• {stats['sessions_before']} session(s) before the purchase (avg duration: {dur})")

            if stats['sessions_during'] > 0:
                dur = self._format_duration(stats['avg_duration_during']) if stats['avg_duration_during'] else "N/A"
                lines.append(f"• {stats['sessions_during']} session(s) during the purchase (avg duration: {dur})")

            if stats['sessions_after'] > 0:
                dur = self._format_duration(stats['avg_duration_after']) if stats['avg_duration_after'] else "N/A"
                lines.append(f"• {stats['sessions_after']} session(s) after the purchase (avg duration: {dur})")

            total_time = self._format_duration(stats['total_time_on_site'])
            lines.append(f"\nTotal time spent on website: {total_time}")

            # Activity stats
            if stats['total_clicks'] > 0 or stats['total_moves'] > 0:
                lines.append(f"User activity: {stats['total_clicks']} clicks, {stats['total_moves']} mouse movements")

            # Previous orders
            if stats['has_previous_orders']:
                lines.append("Note: Customer has previous order history with this merchant")

            if len(stats['unique_ips']) == 1:
                lines.append(f"Consistent IP address used throughout: {stats['unique_ips'][0]}")
            elif len(stats['unique_ips']) > 1:
                lines.append(f"IP addresses used: {', '.join(stats['unique_ips'][:3])}")
        else:
            lines.append(
                "Session data shows the customer accessed the merchant's website to complete this transaction.")

        return '\n'.join(lines)

    def _generate_location_summary_text(self, location: Dict) -> str:
        """Generate human-readable location summary for PDF"""
        lines = []

        if location['ip_address']:
            lines.append(f"Transaction IP Address: {location['ip_address']}")

        loc_parts = []
        if location['city']:
            loc_parts.append(location['city'])
        if location['region']:
            loc_parts.append(location['region'])
        if location['country']:
            loc_parts.append(location['country'])

        if loc_parts:
            lines.append(f"Location: {', '.join(loc_parts)}")

        if location['postal']:
            lines.append(f"Postal Code: {location['postal']}")

        if location['isp']:
            lines.append(f"Internet Service Provider: {location['isp']}")

        if location['timezone']:
            lines.append(f"Timezone: {location['timezone']}")

        if location['is_proxy']:
            lines.append("⚠️ Note: Proxy/VPN detected")
        else:
            lines.append("No proxy or VPN detected - direct connection from residential/commercial IP")

        return '\n'.join(lines)

    def _generate_device_summary_text(self, device: Dict) -> str:
        """Generate human-readable device summary for PDF"""
        lines = []

        if device['device_signature']:
            sig = device['device_signature']
            if isinstance(sig, str) and len(sig) > 50:
                lines.append(f"Device Fingerprint: {sig[:50]}...")
            else:
                lines.append(f"Device Fingerprint: {sig}")

        if device['browsers']:
            lines.append(f"Browser(s): {', '.join(device['browsers'])}")

        if device['operating_systems']:
            lines.append(f"Operating System(s): {', '.join(device['operating_systems'])}")

        if device['is_mobile']:
            lines.append("Device Type: Mobile")
        else:
            lines.append("Device Type: Desktop/Laptop")

        if device['is_bot']:
            lines.append("⚠️ Note: Bot behavior detected")
        elif len(device['user_agents']) == 1:
            lines.append("Consistent device used throughout all sessions")
        elif len(device['user_agents']) > 1:
            lines.append(f"Note: {len(device['user_agents'])} different user agents detected")

        return '\n'.join(lines)


# =============================================================================
# Standalone usage
# =============================================================================

def main():
    extractor = SessionEvidenceExtractor()

    try:
        payment_id = "ec8cd450-96fc-40d6-b8fe-6ba8cb210dd3"  # example
        evidence = extractor.get_session_evidence(payment_id)
        print(json.dumps(evidence, indent=2, default=str))
    finally:
        extractor.close()


if __name__ == "__main__":
    main()