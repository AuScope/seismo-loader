#!/bin/bash

# Update system packages
sudo apt update

# Find available Python version (e.g., 3.10, 3.11, etc.)
PYTHON_VERSION=$(ls /usr/bin | grep -E '^python3\.[0-9]+$' | sort -V | tail -n 1)

if [ -z "$PYTHON_VERSION" ]; then
  echo "No suitable Python version found."
  exit 1
fi

# Install venv for the selected Python version
echo "Installing venv for Python: $PYTHON_VERSION..."
sudo apt install "${PYTHON_VERSION}-venv" -y

# Check if virtual environment already exists
if [ ! -d ".venv" ]; then
  echo "Creating virtual environment..."
  "$PYTHON_VERSION" -m venv .venv
  echo "Virtual environment created."
else
  echo "Virtual environment already exists."
fi

# Activate virtual environment
source .venv/bin/activate

# Install required packages
echo "Installing toml package..."
pip install --upgrade pip
pip install toml

# Generate requirements.txt
echo "Running gen_req.py to generate requirements.txt..."
python gen_req.py || { echo "Failed to run gen_req.py"; exit 1; }

# Install dependencies
echo "Installing dependencies..."
pip install --upgrade pip
pip install -r requirements.txt

echo "Environment setup is complete."
