#!/bin/bash

log_file="/tmp/cloudflared.log"
rm -f "$log_file"

# Start tunnel in background and write logs to file
cloudflared tunnel --url http://localhost:1880 > "$log_file" 2>&1 &

# Wait until the URL appears
while ! grep -q "https://.*\.trycloudflare\.com" "$log_file"; do
    sleep 1
done

# Extract and display the URL
url=$(grep -oE "https://[a-zA-Z0-9.-]+\.trycloudflare\.com" "$log_file" | head -n 1)
echo "Tunnel URL: $url"

