import os
import random
from flask import Flask, jsonify

app = Flask(__name__)
FAIL_RATE = float(os.environ.get("FAIL_RATE", "0"))  # dial up for circuit breaker testing later


@app.route("/pay", methods=["POST"])
def pay():
    if random.random() < FAIL_RATE:
        return jsonify({"error": "payment failed"}), 500
    return jsonify({"status": "success", "service": "payment-service"})


@app.route("/healthz")
def healthz():
    return jsonify({"status": "healthy"}), 200


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
