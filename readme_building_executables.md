
# Building Executables for macOS, Linux, and Windows - Running in Browser Option

This readme outlines the steps to create executables for macOS, Linux, and Windows using **Python**, **Poetry**, and **PyInstaller**. The process is similar across platforms with some platform-specific adjustments.

---

## Initial Setup

### 1. Clean Previous Builds (if necessary)
Before starting, it's good to clean up any previous builds:
```bash
rm -rf dist build *.spec
sudo rm -rf /mnt/c/MyFiles/050-FDSN/seismo-loader/.venv
```

### 2. Install Python, Poetry, and PyInstaller
For each platform (Linux, macOS, Windows):
- Install **Python** from [python.org](https://www.python.org/downloads/).
- Install **Poetry** by running the following command:
  ```bash
  (Invoke-WebRequest -Uri https://install.python-poetry.org -UseBasicParsing).Content | python -
  ```
- Install **PyInstaller** using Poetry or pip:
  ```bash
  poetry add --dev pyinstaller
  ```

### 3. Install Project Dependencies with Poetry
Once Poetry is installed, install all dependencies for your project:
```bash
poetry install
poetry shell
poetry show --with dev
```

---

## Streamlit Adjustments
[https://github.com/jvcss/PyInstallerStreamlit]
### Modify Streamlit to Run in PyInstaller

#### Add Content to `run_app.py`
Create a file called `run_app.py` with the following content:
```python
from streamlit.web import cli

if __name__ == '__main__':
    cli._main_run_clExplicit('seismic_data/ui/main.py', is_hello=False)
```

#### Modify Streamlit's CLI
Navigate to the Streamlit path in your virtual environment:
```
.env\Lib\site-packages\streamlit\web\cli.py
```
Add the following function to `cli.py`:
```python
def _main_run_clExplicit(file, is_hello, args=[], flag_options={}):
    bootstrap.run(file, is_hello, args, flag_options)
```

#### Create a Hook to Collect Streamlit Metadata
Create a new hook file `hook-streamlit.py` under the `./hooks` directory:
```python
from PyInstaller.utils.hooks import copy_metadata

datas = copy_metadata('streamlit')
```

---

## Compile the App with PyInstaller

### For Linux
Use the following command to compile the app on Linux:
```bash
pyinstaller --name seismo-loader \
            --onefile \
            --additional-hooks-dir=./hooks \
            --collect-all streamlit \
            --collect-all folium \
            --collect-all obspy \
            --collect-all streamlit-folium \
            --specpath . \
            --clean \
            run_app.py
```

### For Windows
For Windows, use PowerShell and the following command:
```bash
pyinstaller --name seismo-loader `
            --onefile `
            --additional-hooks-dir=.\hooks `
            --collect-all streamlit `
            --collect-all folium `
            --collect-all obspy `
            --collect-all streamlit-folium `
            --specpath . `
            --clean `
            run_app.py
```

### For macOS
For macOS, the command is similar to Linux:
```bash
pyinstaller --name seismo-loader \
            --onefile \
            --additional-hooks-dir=./hooks \
            --collect-all streamlit \
            --collect-all folium \
            --collect-all obspy \
            --collect-all streamlit-folium \
            --specpath . \
            --clean \
            run_app.py
```

---

## Streamlit Configuration

Create the following configuration file for Streamlit to specify server options.

### `.streamlit/config.toml`:
```toml
[global]
developmentMode = false

[server]
port = 8502
```

Add this file either to the project root or the `dist` output folder after building.

### Copy Configuration and Files
After building, copy configuration and source files to the `dist` folder:
```bash
xcopy /s /e ".\.streamlit" "dist\.streamlit"
Copy-Item -Path "seismic_data" -Destination "dist\seismic_data" -Recurse
```

---

## Modify the Spec File for Each Platform

### Linux Spec File
For Linux, the `datas` and `hiddenimports` sections in the `.spec` file should look like this:
```python
datas = datas + [
    (".venv/lib/python3.12/site-packages/altair/vegalite/v5/schema/vega-lite-schema.json", "./altair/vegalite/v5/schema/"),
    (".venv/lib/python3.12/site-packages/streamlit/static", "./streamlit/static"),
    (".venv/lib/python3.12/site-packages/streamlit/runtime", "./streamlit/runtime"),
    (".venv/lib/python3.12/site-packages/streamlit_folium", "streamlit_folium"),
    ('.venv/lib/python3.12/site-packages/obspy/RELEASE-VERSION', 'obspy/'),
    ("seismic_data", "seismic_data"), 
    ("data", "data"), 
    (".streamlit/config.toml", ".streamlit/config.toml"),
]

hiddenimports = hiddenimports + ['tqdm', 'streamlit-folium', 'pandas', 'requests', 'click', 'tabulate', 'numpy', 'matplotlib', 'pydantic']
```

### Windows Spec File
For Windows, adjust the paths to Windows-style:
```python
datas = datas + [
    (".venv\Lib\site-packages\altair\vegalite\v5\schema\vega-lite-schema.json", "./altair/vegalite/v5/schema/"),
    (".venv\Lib\site-packages\streamlit\static", "./streamlit/static"),
    (".venv\Lib\site-packages\streamlit\runtime", "./streamlit/runtime"),
    (".venv\Lib\site-packages\streamlit_folium", "streamlit_folium"),
    ('.venv\Lib\site-packages\obspy\RELEASE-VERSION', 'obspy/'),
    ("seismic_data", "seismic_data"), 
    ("data", "data"), 
    (".streamlit\config.toml", ".streamlit/config.toml"),
]

hiddenimports = hiddenimports + ['tqdm', 'streamlit-folium', 'pandas', 'requests', 'click', 'tabulate', 'numpy', 'matplotlib', 'pydantic']
```

### macOS Spec File
For macOS, use the same style as Linux, with paths similar to Linux paths:
```python
datas = datas + [
    (".venv/lib/python3.12/site-packages/altair/vegalite/v5/schema/vega-lite-schema.json", "./altair/vegalite/v5/schema/"),
    (".venv/lib/python3.12/site-packages/streamlit/static", "./streamlit/static"),
    (".venv/lib/python3.12/site-packages/streamlit/runtime", "./streamlit/runtime"),
    (".venv/lib/python3.12/site-packages/streamlit_folium", "streamlit_folium"),
    ('.venv/lib/python3.12/site-packages/obspy/RELEASE-VERSION', 'obspy/'),
    ("seismic_data", "seismic_data"), 
    ("data", "data"), 
    (".streamlit/config.toml", ".streamlit/config.toml"),
]

hiddenimports = hiddenimports + ['tqdm', 'streamlit-folium', 'pandas', 'requests', 'click', 'tabulate', 'numpy', 'matplotlib', 'pydantic']
```

---

## Build the Executable

Finally, to build the executable on any platform, run:
```bash
pyinstaller run_app.spec --clean
```

---

## Conclusion

By following these steps, you can build standalone executables for macOS, Linux, and Windows using **Poetry** and **PyInstaller**. Each platform requires slight adjustments, such as path formatting, but the overall process remains consistent across environments.


# Building as Desktop app

## How to build

@stlite/desktop can be used to build a desktop app with Steamlit. Follow the below step:

- Create a `package.json`. There is already one created in the project (see https://github.com/whitphx/stlite/blob/main/packages/desktop/README.md)
- Make sure all required project files are available in `package.json`
- Make sure `requirements.txt` is available for lib dependencies
- `npm install` -> this will install required node_modules
- `npm run dump` -> builds the app
- `npm run serve` -> serves the app
- `npm run dist` -> creates executable

## Main Challenge - Lib dependecies

stlite only accept libraries that have pure wheels, i.e., they are built for webassembly. `pyodide` (https://pyodide.org/en/stable/usage/faq.html#why-can-t-micropip-find-a-pure-python-wheel-for-a-package) seems to be reponsible to bundle the app. This library already comes with a list of famous libs such as `pandas`. But it does not support less famous/widely used libs such as `obspy`.

Packagin a lib in to a webassembly wheel seems to be quite complicated and not worthy of much try. And this is the main blocker of this approach.

**NOTE:** packages with pure wheel will have `*py3-none-any.whl` in their naming.
