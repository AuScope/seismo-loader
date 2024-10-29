FROM python:3.10-slim

WORKDIR /app

RUN apt-get update && apt-get install -y \
    build-essential \
    libgfortran5 \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir poetry

COPY pyproject.toml poetry.lock* ./

RUN poetry config virtualenvs.create false \
    && poetry install --no-interaction --no-ansi
RUN pip install jupyter seaborn

COPY . .

# Expose port for Streamlit
EXPOSE 8501 8888

ENV PYTHONPATH=/app

# Run the Streamlit app
CMD ["sh", "-c", "poetry run streamlit run seed_vault/ui/main.py & jupyter notebook --ip=0.0.0.0 --port=8888 --no-browser --allow-root"]
