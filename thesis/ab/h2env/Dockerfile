# Checker-venv artifact. This is not the image the agent runs in.
# The agent stays on unmodified h1-env:1022. The build stage uses that image
# only so the wheels match its glibc, then the final image is the venv tree.
# At checker time the tree is copied into a cell-private directory. It is not
# present at /opt/h2-checker-venvs while the agent runs.
FROM h1-env:1022 AS build

ENV UV_CACHE_DIR=/opt/uvcache \
    UV_LINK_MODE=copy \
    H2_CHECKER_VENV_ROOT=/opt/h2-checker-venvs

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates curl git libgl1 primer3 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements /opt/h2-checker-requirements
COPY install-checker-deps.sh /opt/h2-install-checker-deps.sh
RUN bash /opt/h2-install-checker-deps.sh /opt/h2-checker-requirements \
    && chmod -R a+rX /opt/h2-checker-venvs

FROM scratch
COPY --from=build /opt/h2-checker-venvs /opt/h2-checker-venvs
