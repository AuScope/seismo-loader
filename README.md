# seed-vault

Seed Vault is a cross platform GUI and CLI utility to download and archive seismic miniseed data via FDSN. Users can download data via earthquake search (station to event, or event to station) as well as download continuous data in bulk. Users can also search and save earthquake catalogs and station metadata. Seed Vault also supports auth requests / accessing restricted data and syncs local SDS data archives with a local sqlite3 database to avoid redundant downloading. Parameters can also be saved an and loaded via a simple text config file. More to come!

## Clone Repository

```bash
git clone https://github.com/AuScope/seed-vault.git
```
or
```bash
git clone git@github.com:AuScope/seed-vault.git
```

## Quick Start

The app requires python >=3.10. For a quick start follow these steps:

```
git clone https://github.com/AuScope/seed-vault.git
cd seed-vault
```

### Linux/MacOS
```
source setup.sh
source run.sh
```
### Windows
Open a powershell and run following commands:
```
.\setup-win.ps1
.\run-win.ps1
```

**Note:** 
1. For Win OS, you would need to convert the shell scripts to PowerShell. Or simply follow the steps in the shell scripts to set up the app.
2. Requires python3 venv software package e.g. For python v10 on Ubuntu you may need to:
   ```
   sudo apt update
   sudo apt install python3.10-venv
   ``` 


## Setting up with Poetry

If you look to further develop this app, it is highly recommended to set up the project with `poetry`. Follow the steps below to set up using `poetry`.

### Install poetry 

Refer to this link: https://python-poetry.org/docs/

Alternatively,

**Linux**
```bash
curl -sSL https://install.python-poetry.org | python3 -
```
then, add following to .bashrc:
```bash
export PATH="$HOME/.local/bin:$PATH"
```

**Windows**
powershell:
```powershell
(Invoke-WebRequest -Uri https://install.python-poetry.org -UseBasicParsing).Content | python -
```
then, add poetry to your system path. It should be located here:
```
%USERPROFILE%\.poetry\bin
```

**Optional**
To configure poetry to create `.venv` inside project folder, run following:

```
poetry config virtualenvs.in-project true
```

## Install pyenv (Optional)
This project uses python 3.12.*. If your base python is a different version (check via `python --version`), you may get errors when trying to install via poetry. Use pyenv to manage this.

**Linux**

Install the required packages for building Python with the following command
```
sudo apt update

sudo apt install -y build-essential libssl-dev zlib1g-dev libbz2-dev
libreadline-dev libsqlite3-dev wget curl llvm libncurses5-dev libncursesw5-dev
xz-utils tk-dev libffi-dev liblzma-dev git
```

Then, install pyenv
```
curl https://pyenv.run | bash
```

After installation, add following to `.bashrc`:
```
export PATH="$HOME/.pyenv/bin:$PATH"

eval "$(pyenv init --path)"

eval "$(pyenv init -)"
```

Run .bashrc to get things updated: `source ~/.bashrc`


### Start the project

Install python 3.12.* if you have a different version locally:

```
pyenv install 3.12.0

pyenv global 3.12.0
```

Confirm your python version: `python --version`

Install the packages using following.

```
poetry install
```

Start the project:
```
poetry shell
```

To run the app:

```
streamlit run seed_vault/ui/main.py
```

Alternatively, command line is configured for this project. You can also run the app, simply by:

```
seed-vault start
```

## Build Project

### Build Python Library

```
poetry build
```

### Build Installers

*Need to be added*

## Docker Development
To develop and run the application using Docker, follow these steps:

### Prerequisites
- Install Docker Application on your system

### Build and Run the Docker Container

1. Navigate to the project root directory:
```bash
cd seed-vault
```

2. Build and run the Docker container:
```bash
docker compose up --build
```
The application should now be running and accessible at `http://localhost:8501`.



## Project Folder structure
```
seed-vault/
│
├── seed_vault/      # Python package containing application code
│   ├── models/        # Python modules for data models
│   ├── service/       # Services for logic and backend processing
│   ├── ui/            # UI components (Streamlit files)
│   ├── utils/         # Utility functions and helpers
│   ├── __init__.py    # 
│   └── cli.py         # Command Line Interface
│
└── pyproject.toml     # Poetry configuration file for the whole project
```

## Export poetry packages to requirements.txt
```
poetry export -f requirements.txt --output requirements.txt --without-hashes
```
