FROM python:3.11-slim

# sqlite3 is included in python:3.11-slim by default
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["python", "bot.py"]
