import os
from flask import Flask, jsonify

app = Flask(__name__)
VERSION = os.environ.get("VERSION", "v1")
_leak = []  # v2 only: intentional memory leak for the assignment's OOMKilled scenario

@app.route("/")
def index():
    if VERSION == "v2":
        _leak.append("x" * 1024 * 1024)  # ~1MB per request, never freed
    return jsonify({"service": "account-service", "version": VERSION, "status": "ok"})

@app.route("/healthz")
def healthz():
    return jsonify({"status": "healthy"}), 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
