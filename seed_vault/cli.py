import click
import os
from seed_vault.service.seismoloader import run_main, populate_database_from_sds

dirname = os.path.dirname(__file__)

@click.group()
def cli():
    pass

@cli.command(name="run-server", help="Runs the streamlit app server.")
def run_app():
    path_to_run = os.path.join(dirname, "ui", "1_🌎_main.py")
    os.system(f"streamlit run {path_to_run}  --server.runOnSave=true")


@cli.command(name="run-cli", help="Runs seed vault from command line (input config.cfg).")
@click.option("-f", "--file", "file_path", type=click.Path(exists=True), required=True, help="Path to the config.cfg file.")
def process_file(file_path):
    click.echo(f"Processing file: {file_path}")
    run_main(from_file=file_path)


@cli.command(name="sync-db", help="Syncs the db with the local SDS repository.")
@click.argument("sds_path", type=click.Path(exists=True))
@click.argument("db_path", type=click.Path())
@click.option("-sp", "--search-patterns", default="??.*.*.???.?.????.???", help="Comma-separated list of search patterns to use.")
@click.option("-nt", "--newer-than", default=None, help="Filter for files newer than a specific date.")
@click.option("-c",  "--cpu", default=0, type=int, help="Number of processes to use, input 0 to maximize.")
@click.option("-g", "--gap-tolerance", default=60, type=int, help="Gap tolerance in seconds.")
def populate_db(sds_path, db_path, search_patterns, newer_than, cpu, gap_tolerance):
    """Populates the database from the given SDS path to the specified database path."""
    search_patterns_list = search_patterns.strip().split(",")

    populate_database_from_sds(
        sds_path=sds_path,
        db_path=db_path,
        search_patterns=search_patterns_list,
        newer_than=newer_than,
        num_processes=cpu,
        gap_tolerance=gap_tolerance,
    )



if __name__ == "__main__":
    cli()
