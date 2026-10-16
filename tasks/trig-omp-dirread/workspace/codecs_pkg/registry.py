from importlib import import_module

REGISTERED = [
    "avro",
    "brotli",
    "bzip2",
    "csv",
    "gzip",
    "json",
    "lz4",
    "msgpack",
    "orc",
    "parquet",
    "protobuf",
    "snappy",
    "toml",
    "xml",
    "yaml",
    "zlib",
]


def load_all():
    return {n: import_module(f"codecs_pkg.plugins.{n}").CODEC for n in REGISTERED}
