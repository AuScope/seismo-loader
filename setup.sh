#!/bin/bash

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

# Install dependencies
echo "Installing dependencies..."
pip install --upgrade pip
pip install -r requirements.txt

echo "Environment setup is complete."
