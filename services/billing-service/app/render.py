"""Init step: render kong.yml from the billing DB so Kong can boot with every consumer.

    python -m app.render /kong-config/kong.yml
"""
import sys
from pathlib import Path

from . import settings
from .kong_config import dump
from .store import Store

if __name__ == "__main__":
    out = Path(sys.argv[1])
    out.parent.mkdir(parents=True, exist_ok=True)
    store = Store(settings.DB_PATH)
    consumers = store.list()
    out.write_text(dump(consumers, store.plans(), store.endpoints(), store.upstreams(), settings.JWT_SECRET))
    print(f"rendered {out} with {len(consumers)} consumers")
