"""
PUBLIC RECORDS FETCHER
public_records.py

Fetches public records data from Redis for phone number verification.
"""

import redis
import json

# Redis configuration
REDIS_CONFIG = {
    "host": "redis-10112.c80.us-east-1-2.ec2.cloud.redislabs.com",
    "port": 10112,
    "password": "ApDjraiWXpFtHiAFvwk2x1wvdWaO5yl5",
    "db": 0,
}


def get_public_records(phone_number):
    """
    Fetch public records from Redis for a phone number.

    Args:
        phone_number: Phone number to lookup (e.g., +15312226997)

    Returns:
        dict with public records data, or None if not found
    """
    if not phone_number:
        return None

    clean_phone = str(phone_number).strip()

    # Ensure it has + prefix
    if not clean_phone.startswith('+'):
        digits = ''.join(filter(str.isdigit, clean_phone))
        if len(digits) == 10:
            clean_phone = f"+1{digits}"
        elif len(digits) == 11 and digits.startswith('1'):
            clean_phone = f"+{digits}"
        else:
            clean_phone = f"+{digits}"

    try:
        r = redis.Redis(**REDIS_CONFIG)

        # Try different key formats
        key_variants = [
            clean_phone,
            f'"{clean_phone}"',
            clean_phone.replace('+', ''),
        ]

        for key in key_variants:
            data = r.get(key)
            if data:
                if isinstance(data, bytes):
                    data = data.decode('utf-8')

                # Handle null/None values
                if data == 'null' or data is None:
                    continue

                try:
                    parsed = json.loads(data)
                    if parsed is None:
                        continue
                    print(f"Found public records for {clean_phone}")
                    return parsed
                except json.JSONDecodeError:
                    return {"name": data}

        return None

    except redis.ConnectionError as e:
        print(f"Redis connection error: {e}")
        return None
    except Exception as e:
        print(f"Error fetching public records: {e}")
        return None


def format_public_records_for_pdf(records):
    """
    Format public records data for display in PDF.

    Args:
        records: Dict with public records data

    Returns:
        Formatted string for PDF display (with HTML tags for reportlab)
    """
    if not records:
        return None

    lines = []

    # Name
    if records.get('name'):
        lines.append(f"<b>Name:</b> {records['name']}")
    elif records.get('firstname'):
        full_name = records.get('firstname', '')
        if records.get('middlename'):
            full_name += f" {records['middlename']}"
        if records.get('lastname'):
            full_name += f" {records['lastname']}"
        lines.append(f"<b>Name:</b> {full_name}")

    # Age range
    if records.get('age_range'):
        lines.append(f"<b>Age Range:</b> {records['age_range']}")

    # Gender
    if records.get('gender'):
        gender = "Female" if records['gender'] == 'F' else "Male" if records['gender'] == 'M' else records['gender']
        lines.append(f"<b>Gender:</b> {gender}")

    # Phone linked since
    if records.get('link_to_phone_start_date'):
        lines.append(f"<b>Phone Linked Since:</b> {records['link_to_phone_start_date']}")

    # Type
    if records.get('type'):
        lines.append(f"<b>Record Type:</b> {records['type']}")

    # Industry
    if records.get('industry'):
        lines.append(f"<b>Industry:</b> {records['industry']}")

    # Alternate names
    if records.get('alternate_names') and len(records['alternate_names']) > 0:
        lines.append(f"<b>Alternate Names:</b> {', '.join(records['alternate_names'])}")

    return "<br/>".join(lines) if lines else None


def create_public_records_table_data(records):
    """
    Create table data for PDF display.

    Args:
        records: Dict with public records data

    Returns:
        List of [label, value] pairs for table
    """
    if not records:
        return []

    table_data = []

    # Name
    if records.get('name'):
        table_data.append(["Name:", records['name']])
    elif records.get('firstname'):
        full_name = records.get('firstname', '')
        if records.get('middlename'):
            full_name += f" {records['middlename']}"
        if records.get('lastname'):
            full_name += f" {records['lastname']}"
        table_data.append(["Name:", full_name])

    # Age range
    if records.get('age_range'):
        table_data.append(["Age Range:", records['age_range']])

    # Gender
    if records.get('gender'):
        gender = "Female" if records['gender'] == 'F' else "Male" if records['gender'] == 'M' else records['gender']
        table_data.append(["Gender:", gender])

    # Phone linked since
    if records.get('link_to_phone_start_date'):
        table_data.append(["Phone Linked Since:", records['link_to_phone_start_date']])

    # Alternate names
    if records.get('alternate_names') and len(records['alternate_names']) > 0:
        table_data.append(["Alternate Names:", ', '.join(records['alternate_names'])])

    return table_data


# Quick test
if __name__ == "__main__":
    phone = input("Phone number to lookup: ").strip()

    records = get_public_records(phone)
    if records:
        print("\nRaw data:")
        print(json.dumps(records, indent=2))

        print("\nFormatted for PDF:")
        formatted = format_public_records_for_pdf(records)
        if formatted:
            print(formatted.replace('<br/>', '\n').replace('<b>', '').replace('</b>', ''))
    else:
        print("No records found")