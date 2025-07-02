from flask import Flask, render_template, jsonify, request
import json
import subprocess
import re

app = Flask(__name__)

# --- WiFi Scanner ---
def scan_wifi():
    try:
        output = subprocess.check_output(["sudo", "iwlist", "wlan0", "scan"], stderr=subprocess.DEVNULL, text=True)
        blocks = output.split("Cell ")
        networks = []

        for block in blocks:
            essid_match = re.search(r'ESSID:"(.*?)"', block)
            quality_match = re.search(r'Quality=(\d+)/(\d+)', block)
            signal_match = re.search(r'Signal level=(-?\d+) dBm', block)
            if essid_match:
                networks.append({
                    "ssid": essid_match.group(1),
                    "quality": round(int(quality_match.group(1)) / int(quality_match.group(2)) * 100) if quality_match else None,
                    "signal": signal_match.group(1) if signal_match else "N/A"
                })

        return networks
    except Exception as e:
        return []

@app.route("/")
def home():
    return render_template("index.html")

@app.route("/wifi-scan")
def wifi_scan():
    return jsonify(scan_wifi())

# Example POST handler (extend as needed)
@app.route("/save-backend", methods=["POST"])
def save_backend():
    data = request.json
    print("Received backend data:", data)

    # Define the file path
    file_path = "/opt/.init/python/backend_data.json"

    # Write data to file
    with open(file_path, "w") as f:
        json.dump(data, f, indent=4)

    return jsonify({"status": "saved"})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=80)
