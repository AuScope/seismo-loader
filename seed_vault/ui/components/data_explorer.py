import streamlit as st
import pandas as pd
import time
import sqlite3
from pathlib import Path
from uuid import uuid4
from collections import deque

from streamlit_ace import st_ace

from seed_vault.models.config import SeismoLoaderSettings
from seed_vault.service.db import DatabaseManager


# @st.cache_data()
def get_queries() -> deque:
    return deque(maxlen=50)

def match_pk_fk(val):
    if not isinstance(val, (int, type(None))):
        raise TypeError(f'Expected type None or int, not {type(val)}, {val =}')
    
    # Assuming the function processes the value to determine primary key/foreign key status
    if val is None:
        return "Not a key"
    elif val == 1:
        return "Primary Key"
    elif val == 2:
        return "Foreign Key"
    else:
        return "Other"

def rename_duplicate_cols(data_frame: pd.DataFrame) -> None:
    """
    for each duplicated column it will add a suffix with a number (col, col_2, col_3... )

    :param data_frame: DataFrame
    :return: None
    """
    new_cols = []
    prev_cols = []  # previously iterated columns in for loop

    for col in data_frame.columns:
        prev_cols.append(col)
        count = prev_cols.count(col)

        if count > 1:
            new_cols.append(f'{col}_{count}')
        else:
            new_cols.append(col)
    data_frame.columns = new_cols

class DataExplorerComponent:
    settings: SeismoLoaderSettings
    db_manager: DatabaseManager
    queries: deque[dict]

    def __init__(self, settings: SeismoLoaderSettings):
        self.settings  = settings
        self.db_manager = DatabaseManager(self.settings.db_path)
        self.queries = get_queries()

    def render_schema(self):
        show_types = st.checkbox('Show types', value=True, help='Show data types for each column ?')
        schema = ''

        with self.db_manager.connection() as conn:
            cursor = conn.cursor()
            tables = cursor.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()

            for x in tables:
                table = x[0]
                schema += f'\n\n * {table}:'

                cursor_table = conn.cursor()
                for row in cursor_table.execute(f"PRAGMA table_info('{table}')"):
                    col_name = row[1]
                    col_type = row[2].upper() if show_types is True else ''
                    schema += f'\n     - {col_name:<15} {col_type} \t {match_pk_fk(row[5])}'

        st.text('DataBase Schema:')
        st.text(schema)


    def render_query_history(self):
        st.write(f'Total Queries: {len(self.queries)}')
        for dct in reversed(self.queries):
            st.markdown('---')
            cols = st.columns(3)
            # cols[0].text(dct['time'])  # server time is not synchronized with the user's timezone
            cols[1].text(f'Exec time: {dct["exec_time_ms"]}ms')
            cols[2].text(f'Message: {dct["message"]}')
            st.markdown(f'```sql \n{dct["query"]} \n```')
    

    def render_query(self):
        with st.container():
            # query = st.text_area(
            #     label='SQL Query',
            #     value='SELECT * FROM archive_data LIMIT 10',
            #     height=160,
            #     key='query',
            #     help='All queries are executed by the SQLite3 engine. Drag the bottom right corner to expand the window'
            # )
            query = st_ace(
                value="SELECT * FROM archive_data LIMIT 10",
                language="sql",
                # theme="monokai",
                key="ace_sql_editor"
            )
            timer_start = time.perf_counter()

            if query:
                try:                    
                    has_error, message, df = self.db_manager.execute_query(query)
                except Exception as E:
                    st.warning(E)
                else:
                    # display dataframe and stats
                    ms_elapsed = int((time.perf_counter() - timer_start) * 1000)
                    cols = st.columns([1,1,2])
                    cols[0].text(f'Exec time: {ms_elapsed}ms')
                    cols[1].text(f'Last Query: {time.strftime("%X")}')
                    cols[2].text(f'Message: {message}')

                    if has_error:
                        st.error(message)
                    else:
                        st.success(message)

                    if df is not None:
                        if df.columns.has_duplicates:
                            rename_duplicate_cols(df)
                        st.dataframe(df)

                    # save query and stats for query-history tab
                    if len(self.queries) == 0 or (len(self.queries) > 0 and query != self.queries[-1]['query']):
                        self.queries.append(
                            {'time': time.strftime("%X"), 'query': query, 'exec_time_ms': ms_elapsed, 'message': message})


    def render_example_queries(self):
        c1,c2 = st.columns([1,1])
        with c1:
            with st.expander("SELECT", expanded=True):
                st.code("SELECT * FROM archive_data", language="sql")
                st.code("SELECT * FROM arrival_data", language="sql")
                st.code("SELECT * FROM archive_data LIMIT 100", language="sql")
                st.code("SELECT DISTINCT network, station FROM archive_data", language="sql")
        with c2:
            with st.expander("DELETE", expanded=True):
                st.code('DELETE FROM archive_data where network="IU" and station="DAV"', language="sql")

    
    def render(self):
        tab1, tab2, tab3, tab4 = st.tabs(['Execute SQL', 'Query History', 'DB Schema', 'Example Queries'])
        with tab1:
            self.render_query()
        with tab2:
            self.render_query_history()
        with tab3:
            self.render_schema()
        with tab4:
            self.render_example_queries()

        