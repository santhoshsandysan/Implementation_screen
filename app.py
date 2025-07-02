from flask import Flask, render_template, jsonify, request
import json
import subprocess
import re

app = Flask(__name__)

# --- Helpers to extract info ---
def extract_ip(ifconfig_data):
    match = re.search(r'inet (\d+\.\d+\.\d+\.\d+)', ifconfig_data)
    return match.group(1) if match else "N/A"

def extract_gateway():
    try:
        output = subprocess.check_output(["ip", "route"], text=True)
        match = re.search(r'default via (\d+\.\d+\.\d+\.\d+)', output)
        return match.group(1) if match else "N/A"
    except:
        return "N/A"

def extract_dns():
    try:
        with open("/etc/resolv.conf") as f:
            lines = f.readlines()
        return [line.split()[1] for line in lines if line.startswith("nameserver")]
    except:
        return []

# --- WiFi Scanner ---
def scan_wifi():
    try:
        output = subprocess.check_output(
            ["sudo", "iwlist", "wlan0", "scan"],
            stderr=subprocess.DEVNULL,
            text=True
        )
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
        print("WiFi scan error:", e)
        return []

# --- Routes ---
@app.route("/")
def home():
    return render_template("index.html")

@app.route("/wifi-scan")
def wifi_scan():
    return jsonify(scan_wifi())

@app.route("/list-hardware", methods=["GET"])
def list_hardware():
    interface = request.args.get("iface")
    if not interface:
        return jsonify({"error": "Missing 'iface' parameter"}), 400

    try:
        raw_data = subprocess.check_output(["ifconfig", interface], text=True)
        ip = extract_ip(raw_data)
        gateway = extract_gateway()
        dns = extract_dns()

        return jsonify({
            "interface": interface,
            "ip_address": ip,
            "gateway": gateway,
            "dns": dns
        })

    except subprocess.CalledProcessError:
        return jsonify({"error": f"Interface '{interface}' not found or inactive"}), 404
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/save-hardware", methods=["POST"])
def save_hardware():
    data = request.json
    print("Received hardware data:", data)
    return jsonify({"status": "saved"})

@app.route("/save-backend", methods=["POST"])
def save_backend():
    data = request.json
    print("Received backend data:", data)

    file_path = "/opt/.init/python/backend_data.json"
    try:
        with open(file_path, "w") as f:
            json.dump(data, f, indent=4)
        return jsonify({"status": "saved"})
    except Exception as e:
        print("Error writing file:", e)
        return jsonify({"status": "error", "message": str(e)}), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=80)
