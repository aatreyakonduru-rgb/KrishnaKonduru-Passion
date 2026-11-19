FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends git && rm -rf /var/lib/apt/lists/*
# Optional OCR for scanned PDFs (local only):
# RUN apt-get update && apt-get install -y --no-install-recommends tesseract-ocr && pip install pytesseract pillow pymupdf

WORKDIR /app
COPY . /app
# .gitmodules is copied above; fetch the framework submodule (needs credentials at build time)
RUN git submodule update --init --recursive || true
RUN pip install --no-cache-dir -r requirements.txt

EXPOSE 8080 8090
CMD ["python", "main.py"]
