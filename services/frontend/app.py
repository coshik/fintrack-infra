import os, requests
from flask import Flask, jsonify

app = Flask(__name__)
ACCOUNT_URL = os.environ.get("ACCOUNT_SERVICE_URL", "http://account-service:5000")
PAYMENT_URL = os.environ.get("PAYMENT_SERVICE_URL", "http://payment-service:5000")

@app.route("/")
def index():
    try:
        account_resp = requests.get(f"{ACCOUNT_URL}/", timeout=2).json()
        payment_resp = requests.post(f"{PAYMENT_URL}/pay", timeout=2).json()
        return jsonify({"account": account_resp, "payment": payment_resp})
    except requests.exceptions.RequestException as e:
        return jsonify({"error": str(e)}), 502

@app.route("/healthz")
def healthz():
    return jsonify({"status": "healthy"}), 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
