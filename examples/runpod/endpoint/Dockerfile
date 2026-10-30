FROM pytorch/pytorch:2.6.0-cuda12.6-cudnn9-runtime@sha256:f894dae26e1ee8557c544f9cfdb9dc011b1552bf3c1e656b422f2e221d380e40

WORKDIR /app

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY quickstart_worker.py matrix_worker.py /app/

ARG WORKER_SCRIPT=matrix_worker.py
ENV WORKER_SCRIPT=${WORKER_SCRIPT}

CMD ["sh", "-c", "python -u /app/${WORKER_SCRIPT}"]
