"""
CHARGEBACK RESPONSE API
Flask API that generates chargeback PDFs (no screenshots/Playwright).

Endpoints:
    POST /generate         - Generate a chargeback PDF for a payment ID
    GET  /download/<name>  - Download a generated PDF
    GET  /health           - Health check

Usage:
    python api.py
    # Runs on http://0.0.0.0:5000

Example:
    curl -X POST http://localhost:5000/generate \
         -H "Content-Type: application/json" \
         -d '{"paymentid": "4c85a19d-7f55-4010-ad3c-a6b0e88d0560"}'
"""

import os
import uuid
import traceback
from flask import Flask, request, jsonify, send_from_directory

# Import the no-screenshots processor
from main_no_screenshots import process_chargeback

app = Flask(__name__)

# Directory where generated PDFs are stored
OUTPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "generated_pdfs")
os.makedirs(OUTPUT_DIR, exist_ok=True)


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"})


@app.route("/generate", methods=["POST"])
def generate():
    """
    Generate a chargeback PDF.

    Request body:
        {"paymentid": "xxx-xxx-xxx"}

    Returns:
        {"success": true, "download_url": "/download/chargeback_fraud_12345.pdf", "filename": "..."}
    """
    data = request.get_json(silent=True)
    if not data or not data.get("paymentid"):
        return jsonify({"success": False, "error": "Missing 'paymentid' in request body"}), 400

    paymentid = data["paymentid"].strip()
    if not paymentid:
        return jsonify({"success": False, "error": "Empty paymentid"}), 400

    try:
        # process_chargeback returns a path like "chargeback_fraud_12345.pdf"
        # We need to override the output to land in our OUTPUT_DIR
        original_cwd = os.getcwd()
        os.chdir(OUTPUT_DIR)

        try:
            result_path = process_chargeback(paymentid)
        finally:
            os.chdir(original_cwd)

        if not result_path:
            return jsonify({"success": False, "error": "Failed to generate PDF"}), 500

        # result_path might include subdirs like "pnr_test/chargeback_pnr_xxx.pdf"
        filename = os.path.basename(result_path)
        full_path = os.path.join(OUTPUT_DIR, result_path)

        if not os.path.exists(full_path):
            return jsonify({"success": False, "error": f"PDF not found at expected path: {result_path}"}), 500

        download_url = f"/download/{filename}"

        return jsonify({
            "success": True,
            "download_url": download_url,
            "filename": filename,
            "paymentid": paymentid,
        })

    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/download/<filename>", methods=["GET"])
def download(filename):
    """Download a generated PDF."""
    # Prevent path traversal
    if ".." in filename or "/" in filename:
        return jsonify({"error": "Invalid filename"}), 400

    # Search in OUTPUT_DIR and subdirs
    for root, dirs, files in os.walk(OUTPUT_DIR):
        if filename in files:
            return send_from_directory(root, filename, as_attachment=True)

    return jsonify({"error": "File not found"}), 404


if __name__ == "__main__":
    print("=" * 50)
    print("CHARGEBACK RESPONSE API")
    print("=" * 50)
    print(f"Output dir: {OUTPUT_DIR}")
    print(f"Endpoints:")
    print(f"  POST /generate       - Generate PDF")
    print(f"  GET  /download/<name> - Download PDF")
    print(f"  GET  /health         - Health check")
    print("=" * 50)

    app.run(host="0.0.0.0", port=5000, debug=False)
