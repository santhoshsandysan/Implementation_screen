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

@app.route("/current-wifi")
def current_wifi():
    try:
        ssid = subprocess.check_output(["iwgetid", "-r"], text=True).strip()
        return jsonify({"ssid": ssid if ssid else "Not Connected"})
    except Exception as e:
        return jsonify({"ssid": "Unknown", "error": str(e)})


@app.route("/connect-wifi", methods=["POST"])
def connect_wifi():
    data = request.json
    ssid = data.get("ssid")
    password = data.get("password")

    if not ssid or not password:
        return jsonify({"status": "error", "message": "Missing SSID or password"}), 400

    # Use wpa_supplicant to connect (overwrite config)
    try:
        wpa_conf = f"""
        ctrl_interface=DIR=/var/run/wpa_supplicant GROUP=netdev
        update_config=1
        country=IN

        network={{
            ssid="{ssid}"
            psk="{password}"
        }}
        """
        with open("/etc/wpa_supplicant/wpa_supplicant.conf", "w") as f:
            f.write(wpa_conf)

        # Restart Wi-Fi interface (may vary by system)
        subprocess.call(["sudo", "wpa_cli", "-i", "wlan0", "reconfigure"])
        return jsonify({"status": "connected"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})


@app.route("/save-hardware", methods=["POST"])
def save_hardware():
    data = request.json
    print("Received hardware data:", data)

    interface = data.get("ethernetLabel") or "eth0"
    ip = data.get("hardware_ip")
    gateway = data.get("gateway")
    dns = data.get("dns", "")

    if not ip or not gateway:
        return jsonify({"status": "error", "message": "Missing IP or Gateway"}), 400

    try:
        # Build the static config
        static_config = f"""
interface {interface}
static ip_address={ip}/24
static routers={gateway}
"""

        # Read current config
        with open("/etc/dhcpcd.conf", "r") as file:
            current_config = file.read()

        # Remove any existing block for the same interface
        updated_config = re.sub(
            rf"(?s)#?interface {re.escape(interface)}.*?(?=\ninterface|\Z)",
            "", current_config
        ).strip()

        # Append the new static ifco    
        updated_config += "\n\n" + static_config.strip() + "\n"

        # Write the updated config
        with open("/etc/dhcpcd.conf", "w") as file:
            file.write(updated_config)

        return jsonify({"status": "saved and written to dhcpcd.conf"})

    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


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
