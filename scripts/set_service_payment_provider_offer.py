"""Configure standalone Lava.top routing using an operator's database access."""

import argparse
from collections.abc import Sequence
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from app.core.db import SessionLocal  # noqa: E402
from app.services.payment_provider_offer_service import (  # noqa: E402
    PaymentProviderOfferInputError,
    PaymentProviderOfferPersistenceError,
    set_lava_top_standalone_offer,
)


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--service-addon-id", required=True, type=int)
    parser.add_argument("--external-offer-id", required=True)
    args = parser.parse_args(argv)

    with SessionLocal() as db:
        try:
            change = set_lava_top_standalone_offer(
                db,
                service_addon_id=args.service_addon_id,
                external_offer_id=args.external_offer_id,
            )
        except PaymentProviderOfferInputError as exc:
            parser.exit(1, f"failed: {exc}\n")
        except PaymentProviderOfferPersistenceError:
            parser.exit(1, "failed: provider offer mapping could not be persisted.\n")
    print(f"{change}: service_addon_id={args.service_addon_id} provider=lava_top")


if __name__ == "__main__":
    main()
