FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y \
    build-essential \
    libgfortran5 \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir poetry

COPY pyproject.toml poetry.lock* ./

RUN poetry config virtualenvs.create false \
    && poetry install --no-interaction --no-ansi

COPY . .

# Expose port for Streamlit
EXPOSE 8501

ENV PYTHONPATH=/app

# Run the Streamlit app
CMD ["poetry", "run", "streamlit", "run", "seismic_data/ui/main.py"]