# SPDX-License-Identifier: Apache-2.0
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY --chmod=0644 main.py card.py skills.py onboard.py agent-card.json ./
USER nobody
EXPOSE 8055
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8055"]
