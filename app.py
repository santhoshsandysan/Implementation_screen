from flask import Flask, render_template, jsonify, request
import json
import subprocess
import os
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

def read_from_dhcpcd(interface):
    """Reads IP, gateway, and DNS from /etc/dhcpcd.conf if present."""
    ip = gateway = None
    dns_list = []

    if not os.path.exists("/etc/dhcpcd.conf"):
        return None, None, []

    with open("/etc/dhcpcd.conf", "r") as f:
        lines = f.readlines()

    iface_found = False
    for line in lines:
        line = line.strip()

        # Find the interface block
        if line.startswith("interface") and interface in line:
            iface_found = True
        elif iface_found:
            if line.startswith("static ip_address"):
                ip = line.split("=")[1].strip().split("/")[0]  # remove subnet mask
            elif line.startswith("static routers"):
                gateway = line.split("=")[1].strip()
            elif line.startswith("static domain_name_servers"):
                dns_list = line.split("=")[1].strip().split(" ")
            elif line.startswith("interface"):  
                break  # stop when we hit another interface section

    return ip, gateway, dns_list

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
        # ✅ 1️⃣ First try dhcpcd.conf
        ip, gateway, dns = read_from_dhcpcd(interface)

        # ✅ 2️⃣ Fallback to ifconfig for IP if not found in dhcpcd
        if not ip:
            try:
                raw_data = subprocess.check_output(["ifconfig", interface], text=True)
                ip_match = re.search(r"inet (\d+\.\d+\.\d+\.\d+)", raw_data)
                ip = ip_match.group(1) if ip_match else None
            except subprocess.CalledProcessError:
                return jsonify({"error": f"Interface '{interface}' not found or inactive"}), 404

        # ✅ 3️⃣ Get gateway if not found in dhcpcd
        if not gateway:
            try:
                route_data = subprocess.check_output(["ip", "route"], text=True)
                gw_match = re.search(r"default via (\d+\.\d+\.\d+\.\d+)", route_data)
                gateway = gw_match.group(1) if gw_match else None
            except subprocess.CalledProcessError:
                gateway = None

        # ✅ 4️⃣ Get DNS if not found in dhcpcd
        if not dns:
            try:
                with open("/etc/resolv.conf") as f:
                    dns = [line.split()[1] for line in f if line.startswith("nameserver")]
            except FileNotFoundError:
                dns = []

        return jsonify({
            "interface": interface,
            "ip_address": ip,
            "gateway": gateway,
            "dns": dns
        })

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

@app.route("/reboot", methods=["GET"])
def reboot():
    os.system("sudo reboot")
    return "Rebooting system..."

@app.route('/check-machine-limit')
def check_machine_limit():
    device_file = "/opt/device_id.txt"

    try:
        with open(device_file, "r") as f:
            device_id = f.read().strip()   # e.g. "YC-D-M4-LWC-IO-0020"
    except FileNotFoundError:
        return jsonify({"status": "error", "message": "Device ID file not found!"})

    # ✅ Extract the machine limit right after 'M'
    import re
    match = re.search(r'M(\d+)', device_id)
    if match:
        max_limit = int(match.group(1))   # → gets the number after M
    else:
        return jsonify({"status": "error", "message": "Machine limit not found in device ID."})

    # ✅ Get count from query
    count = int(request.args.get('count', 0))

    # ✅ Compare against extracted limit
    if count > max_limit:
        return jsonify({"status": "error", "message": f"Limit exceeded! Max allowed: {max_limit}."})
    else:
        return jsonify({"status": "ok", "max_allowed": max_limit})
    
@app.route('/save-machine', methods=['POST'])
def save_machine():
    """✅ Save each machine individually into its own JSON file"""
    data = request.get_json()

    # Extract fields
    machine_name = data.get("machine_name")
    machine_ip = data.get("machine_ip")
    reason_id = data.get("reason_id")
    operator_id = data.get("operator_id")
    routecard_id = data.get("routecard_id")

    # ✅ Validate
    if not machine_name:
        return jsonify({"status": "error", "message": "Machine name is required!"}), 400

    # ✅ Ensure machines folder exists
    machine_folder = "/opt/python/machines"
    os.makedirs(machine_folder, exist_ok=True)

    # ✅ Clean machine_name for filename (no spaces or weird chars)
    safe_name = re.sub(r'[^A-Za-z0-9_-]', '_', machine_name)
    file_path = os.path.join(machine_folder, f"{safe_name}.json")

    # ✅ Prepare JSON data
    machine_record = {
        "machine_name": machine_name,
        "machine_ip": machine_ip,
        "reason_id": reason_id,
        "operator_id": operator_id,
        "routecard_id": routecard_id
    }

    try:
        # ✅ Write machine record to its own JSON file
        with open(file_path, "w") as f:
            json.dump(machine_record, f, indent=4)

        print(f"[✅] Machine saved: {machine_name} → {file_path}")
        return jsonify({"status": "ok", "message": f"{machine_name} saved in {file_path}"})

    except Exception as e:
        print(f"[❌] Error saving {machine_name}:", e)
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/reset-machines', methods=['GET'])
def reset_machines():
    folder = "/opt/python/machines"
    try:
        if os.path.exists(folder):
            for file in os.listdir(folder):
                file_path = os.path.join(folder, file)
                if os.path.isfile(file_path) and file_path.endswith(".json"):
                    os.remove(file_path)
        return jsonify({"status": "ok", "message": "All machine files deleted"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})


@app.route("/machines")
def machines():
    return render_template("machine_list.html")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=80)
