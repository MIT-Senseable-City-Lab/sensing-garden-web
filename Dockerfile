FROM python:3.9-slim
WORKDIR /app

# Install Poetry
RUN pip install poetry==1.6.1

# Configure Poetry to not create a virtual environment inside the container
RUN poetry config virtualenvs.create false

# Copy only dependencies first to leverage Docker cache
COPY pyproject.toml poetry.lock* ./

# Install dependencies
RUN poetry install --no-dev --no-interaction --no-ansi

# Copy application files
COPY . .

# Set environment variables
ENV FLASK_APP=app.py
ENV FLASK_ENV=production

EXPOSE 5052
CMD ["gunicorn", "--bind", "0.0.0.0:5052", "--timeout", "120", "app:app"]
