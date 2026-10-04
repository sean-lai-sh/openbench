from __future__ import annotations


_NAMES = {
    "badlogic/pi-mono": "pi",
    "earendil-works/pi": "pi",
    "can1357/oh-my-pi": "omp",
}

_CLONES = {
    "pi": (
        "https://github.com/earendil-works/pi.git",
        "https://github.com/badlogic/pi-mono.git",
    ),
    "omp": ("https://github.com/can1357/oh-my-pi.git",),
}

_LAYOUT = {
    "pi": {
        "agent_env": "PI_CODING_AGENT_DIR",
        "home_dir": ".pi",
        "exe": "pi",
        "models_filename": "models.json",
    },
    "omp": {
        "agent_env": "OMP_CODING_AGENT_DIR",
        "home_dir": ".omp",
        "exe": "omp",
        "models_filename": "models.yml",
    },
}


def harness_name(repo: str) -> str:
    if not repo:
        return "opencode"
    try:
        return _NAMES[repo]
    except KeyError:
        raise KeyError(repo) from None


def clone_urls(name: str) -> tuple[str, ...]:
    return _CLONES[name]


def agent_layout(name: str) -> dict:
    return dict(_LAYOUT[name])
