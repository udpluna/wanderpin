#!/bin/bash
cd "$(dirname "$0")"
python3 -m venv venv && source venv/bin/activate
pip install --upgrade pip setuptools wheel && pip install -r requirements.txt
echo "Done. Run ./start_mac.sh"
