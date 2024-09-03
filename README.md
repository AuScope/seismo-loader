# Seismo-Loader

*Add a brief intro here*

## Set up Development

### Clone the repository:
```bash
git clone https://github.com/AuScope/seismo-loader.git
```
or
```bash
git clone git@github.com:AuScope/seismo-loader.git
```

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
streamlit run seismic_data/ui/main.py
```

Alternatively, command line is configured for this project. You can also run the app, simply by:

```
seismo-loader start
```

## Build Project

### Build Python Library

```
poetry build
```

### Build Installers

*Need to be added*


## Project Folder structure
```
seismo-loader/
│
├── seismic_data/      # Python package containing application code
│   ├── models/        # Python modules for data models
│   ├── service/       # Services for logic and backend processing
│   ├── ui/            # UI components (Streamlit files)
│   ├── utils/         # Utility functions and helpers
│   ├── __init__.py    # 
│   └── cli.py         # Command Line Interface
│
└── pyproject.toml     # Poetry configuration file for the whole project
```

