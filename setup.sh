#!/bin/bash

# Update system packages (macOS doesn't need `apt update`)
if [[ "$OSTYPE" == "linux-gnu"* ]]; then
  sudo apt update
elif [[ "$OSTYPE" == "darwin"* ]]; then
  echo "Updating Homebrew packages..."
  brew update
fi

# Find available Python version (e.g., 3.10, 3.11, etc.)
PYTHON_VERSION=$(ls /usr/bin | grep -E '^python3\.[0-9]+$' | sort -V | tail -n 1)

if [ -z "$PYTHON_VERSION" ]; then
  echo "Error: No suitable Python version found."
  return
fi

# Check if the Python version is above 3.10
PYTHON_MAJOR_VERSION=$(echo $PYTHON_VERSION | grep -oE '[0-9]+' | head -n 1)
PYTHON_MINOR_VERSION=$(echo $PYTHON_VERSION | grep -oE '[0-9]+' | sed -n 2p)

if [ "$PYTHON_MAJOR_VERSION" -lt 3 ] || ( [ "$PYTHON_MAJOR_VERSION" -eq 3 ] && [ "$PYTHON_MINOR_VERSION" -lt 10 ] ); then
  echo "Error: Python version must be 3.10 or higher. Found: $PYTHON_VERSION"
  return
fi

# Install venv for the selected Python version (macOS uses Homebrew for installations)
echo "Installing venv for Python: $PYTHON_VERSION..."
if [[ "$OSTYPE" == "linux-gnu"* ]]; then
  sudo apt install "${PYTHON_VERSION}-venv" -y
elif [[ "$OSTYPE" == "darwin"* ]]; then
  brew install python@${PYTHON_VERSION:7:2}
fi

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
