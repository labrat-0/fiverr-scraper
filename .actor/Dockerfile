FROM apify/actor-python:3.12

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
# Patchright ships its own patched Chromium; install it plus vanilla as fallback.
RUN patchright install chromium --with-deps
RUN playwright install chromium

COPY . ./

CMD ["python", "-m", "src"]