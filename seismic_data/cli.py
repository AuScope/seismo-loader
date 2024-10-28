import click
import os

dirname = os.path.dirname(__file__)

@click.group()
def cli():
    pass

@cli.command()
def start():
    print(dirname)
    path_to_run = os.path.join(dirname, "ui", "main.py")
    os.system(f"streamlit run {path_to_run}  --server.runOnSave=true")

if __name__ == "__main__":
    cli()
