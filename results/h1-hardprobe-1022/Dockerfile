# H1 hard-pack env: union of the 9 Harbor task images (pre-reg v2 dated note: CPU VM, Docker exec).
FROM python:3.13-bookworm
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl git jq unzip build-essential rustc g++ tmux asciinema primer3 \
    chromium chromium-driver libgl1 libglib2.0-0 libsm6 libxext6 libxrender1 ca-certificates \
 && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir numpy==2.2.5 chess selenium==4.35.0 beautifulsoup4==4.13.4 \
    "opencv-contrib-python>=4.11.0.86" \
 && pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu
RUN curl -LsSf https://astral.sh/uv/0.9.5/install.sh | sh
ENV PATH=/root/.local/bin:$PATH
