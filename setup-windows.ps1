# Update system packages (not applicable for Windows)

# Find Python version (assuming Python is installed and accessible in the PATH)
$pythonVersion = &python -V 2>&1
if ($pythonVersion -notmatch "Python 3\.\d+") {
    Write-Output "No suitable Python version found."
    exit 1
}

# Check if virtual environment already exists
if (-not (Test-Path ".venv")) {
    Write-Output "Creating virtual environment..."
    python -m venv .venv
    Write-Output "Virtual environment created."
} else {
    Write-Output "Virtual environment already exists."
}

# Activate virtual environment
& .\.venv\Scripts\Activate

# Install required packages
Write-Output "Installing toml package..."
pip install --upgrade pip
pip install toml

# Generate requirements.txt
Write-Output "Running gen_req.py to generate requirements.txt..."
try {
    python gen_req.py
} catch {
    Write-Output "Failed to run gen_req.py"
    exit 1
}

# Install dependencies
Write-Output "Installing dependencies..."
pip install --upgrade pip
pip install -r requirements.txt

Write-Output "Environment setup is complete."
