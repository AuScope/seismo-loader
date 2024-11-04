#!/bin/bash

sudo apt update
sudo apt install python3.10-venv 
# Check if virtual environment already exists
if [ ! -d "venv" ]; then
  echo "Creating virtual environment..."
  python3 -m venv .venv
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
