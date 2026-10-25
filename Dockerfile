# syntax=docker/dockerfile:1
#
# grift-cli container image, built from this checkout.
#
#   docker build -t grift-cli .
#   docker run --rm -v "$PWD:/repo" grift-cli repo
#
# The analysed repository is mounted at /repo. grift calls git with
# `-c safe.directory=*`, so a host UID that differs from the image user does
# not block reads; pass `--user "$(id -u):$(id -g)"` when writing with --out.

FROM python:3.12-slim AS build
WORKDIR /src
RUN python -m pip install --no-cache-dir build
# Only the wheel inputs: the version comes from src/tep_core/version.py, so
# the build needs no git history.
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
RUN python -m build --wheel --outdir /dist

FROM python:3.12-slim
LABEL org.opencontainers.image.source="https://github.com/Cor-Incorporated/grift-cli" \
      org.opencontainers.image.description="Deterministic TEP evidence metrics from a single git repository. No LLM." \
      org.opencontainers.image.licenses="MIT"

# git is required; openssh-client provides ssh-keygen for `grift attest`
# OpenSSH signing. gh and cosign are optional network paths and not bundled.
RUN apt-get update \
    && apt-get install -y --no-install-recommends git openssh-client \
    && rm -rf /var/lib/apt/lists/*

COPY --from=build /dist/*.whl /tmp/
RUN python -m pip install --no-cache-dir /tmp/*.whl && rm /tmp/*.whl

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN groupadd --gid 1000 grift \
    && useradd --uid 1000 --gid grift --create-home --home-dir /home/grift grift
USER grift

WORKDIR /repo
ENTRYPOINT ["grift"]
CMD ["--help"]
