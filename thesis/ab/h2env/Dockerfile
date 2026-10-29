# H2 cell image. h1-env:1022 plus one virtualenv per hard-suite checker.
# Harbor test.sh cold-installed torch (and numpy, MobileSAM, opencv, …) with
# uvx at check time and was killed by the 120s checker cap. Those pins live in
# requirements/. test.sh uses /opt/h2-checker-venvs/<task>/bin/python when it
# is present and does not pip-install.
FROM h1-env:1022

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
    && chmod -R a+rX /opt/h2-checker-venvs /opt/uvcache
