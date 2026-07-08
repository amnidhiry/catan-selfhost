FROM python:3.12-slim

WORKDIR /app

# git is needed to pip-install catanatron straight from GitHub (below);
# python:*-slim doesn't ship it.
RUN apt-get update \
    && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*

# Pin catanatron to a specific commit for reproducibility. PyPI lacks the
# domestic-trade actions (OFFER/ACCEPT/CONFIRM_TRADE) this project needs — they
# exist only on the GitHub repo. Do NOT use a bare "master": the engine's API
# drifts (e.g. it dropped `state.discard_counts` and the `DISCARD_RESOURCE`
# action), which silently breaks the serializer. Bump this hash deliberately
# and re-run the smoke tests after.
ARG CATANATRON_REF=82aae93ab1f7c267218be0566df573ce477ec3d8
RUN pip install --no-cache-dir \
    "fastapi>=0.110" "uvicorn[standard]>=0.29" \
    "git+https://github.com/bcollazo/catanatron.git@${CATANATRON_REF}"

COPY server/ server/

VOLUME /data
EXPOSE 8000
CMD ["uvicorn", "server.main:app", "--host", "0.0.0.0", "--port", "8000"]
