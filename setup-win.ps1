# Update system packages (not applicable for Windows)

# Find Python version (assuming Python is installed and accessible in the PATH)
$pythonVersion = &python -V 2>&1
if ($pythonVersion -notmatch "Python 3\.\d+") {
    Write-Output "Error: No suitable Python version found."
    return
}

# Check if the Python version is above 3.10
if ($pythonVersion -match "Python 3\.(\d+)") {
    $minorVersion = [int]$matches[1]
    if ($minorVersion -lt 10) {
        Write-Output "Error: Python version must be 3.10 or higher. Found: $pythonVersion"
        return
    }
}
else {
    Write-Output "Error: Failed to determine Python version."
    return
}

# Check if virtual environment already exists
if (-not (Test-Path ".venv")) {
    Write-Output "Creating virtual environment..."
    python -m venv .venv
    Write-Output "Virtual environment created."
}
else {
    Write-Output "Virtual environment already exists."
}

# Activate virtual environment
& .\.venv\Scripts\Activate

# Upgrade pip using Python
Write-Output "Upgrading pip..."
& .\.venv\Scripts\python.exe -m pip install --upgrade pip

# Install required packages
Write-Output "Installing toml package..."
& .\.venv\Scripts\python.exe -m pip install toml

# Generate requirements.txt
Write-Output "Running gen_req.py to generate requirements.txt..."
try {
    & .\.venv\Scripts\python.exe gen_req.py
}
catch {
    Write-Output "Failed to run gen_req.py"
    exit 1
}

# Install dependencies
Write-Output "Installing dependencies..."
& .\.venv\Scripts\python.exe -m pip install -r requirements.txt

Write-Output "Environment setup is complete."
