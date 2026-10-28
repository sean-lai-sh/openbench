FROM h1-env:1022
RUN apt-get update -qq && apt-get install -y -qq strace && rm -rf /var/lib/apt/lists/* && strace -V | head -1
LABEL obench.image=h1-env:1027-strace obench.base=h1-env:1022
