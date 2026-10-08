import os
from concurrent.futures import ThreadPoolExecutor

import requests
from flask import Flask, jsonify, request

app = Flask(__name__)
ACCOUNT_URL = os.environ.get("ACCOUNT_SERVICE_URL", "http://account-service:5000")
PAYMENT_URL = os.environ.get("PAYMENT_SERVICE_URL", "http://payment-service:5000")

TRACE_HEADERS = [
    "x-request-id", "x-b3-traceid", "x-b3-spanid", "x-b3-parentspanid",
    "x-b3-sampled", "x-b3-flags", "x-ot-span-context",
]

executor = ThreadPoolExecutor(max_workers=4)


def forwarded_headers():
    return {h: request.headers[h] for h in TRACE_HEADERS if h in request.headers}


def call_account(headers):
    return requests.get(f"{ACCOUNT_URL}/", headers=headers, timeout=2).json()


def call_payment(headers):
    return requests.post(f"{PAYMENT_URL}/pay", headers=headers, timeout=2).json()


@app.route("/")
def index():
    # headers must be read here: the request context isn't available in worker threads
    headers = forwarded_headers()
    try:
        account_future = executor.submit(call_account, headers)
        payment_future = executor.submit(call_payment, headers)
        return jsonify({
            "account": account_future.result(),
            "payment": payment_future.result(),
        })
    except requests.exceptions.RequestException as e:
        return jsonify({"error": str(e)}), 502


@app.route("/healthz")
def healthz():
    return jsonify({"status": "healthy"}), 200


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
