FROM python:3.12-slim

WORKDIR /app

# git is needed to pip-install catanatron straight from GitHub (below);
# python:*-slim doesn't ship it.
RUN apt-get update \
    && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*

# Pin catanatron to a specific commit — never a moving ref. The engine's API
# drifts on master: this commit still has per-card discards (DISCARD_RESOURCE)
# and state.discard_counts, which the "choose your discards" feature needs. A
# LATER commit (82aae93) reverted to bulk random-half DISCARD; pinning here
# keeps the deployed engine matching what the tests validate. The code also
# tolerates both discard APIs (server/main.parse_action, DiscardPanel) so a
# future bump can't silently hang a 7-roll — but re-run smoke tests after any.
ARG CATANATRON_REF=41ba0db5bc9d95b13a32e1ed7710094382a3b87a
RUN pip install --no-cache-dir \
    "fastapi>=0.110" "uvicorn[standard]>=0.29" "aenum>=3.1" "anthropic>=0.40" \
    "git+https://github.com/bcollazo/catanatron.git@${CATANATRON_REF}"

COPY server/ server/

VOLUME /data
EXPOSE 8000
CMD ["uvicorn", "server.main:app", "--host", "0.0.0.0", "--port", "8000"]
