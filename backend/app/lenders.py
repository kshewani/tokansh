"""Server-owned fictional lender catalogue; no external credit or banking integration."""
from pydantic import BaseModel, ConfigDict
from app.errors import ApplicationError


class Offer(BaseModel):
    model_config = ConfigDict(frozen=True)
    id: str
    annual_rate_bps: int
    max_ltv_percent: int
    tenures_months: tuple[int, ...]


class Lender(BaseModel):
    id: str
    name: str
    simulated: bool = True
    offers: list[Offer]


LENDERS = [
    Lender(id='axim-bank', name='Axim Bank', offers=[Offer(id='axim-standard', annual_rate_bps=1000, max_ltv_percent=60, tenures_months=(6, 12))]),
    Lender(id='real-finance', name='Real Finance', offers=[Offer(id='real-flex', annual_rate_bps=900, max_ltv_percent=55, tenures_months=(6, 12, 24))]),
    Lender(id='horizon-credit', name='Horizon Credit', offers=[Offer(id='horizon-liquidity', annual_rate_bps=1200, max_ltv_percent=70, tenures_months=(3, 6, 12))]),
]
DEFAULT_LENDER = 'axim-bank'


def lender(lender_id):
    for item in LENDERS:
        if item.id == lender_id:
            return item
    raise ApplicationError(422, 'INVALID_LENDER', 'Select a supported demo lender workspace.')


def terms(command):
    institution = lender(command.lender_id)
    offer = next((o for o in institution.offers if o.id == command.offer_id), None)
    if (offer is None or command.annual_rate_bps != offer.annual_rate_bps
            or command.ltv_percent > offer.max_ltv_percent or command.term_months not in offer.tenures_months):
        raise ApplicationError(422, 'INVALID_OFFER', 'Select a listed lender offer, rate, supported tenure and LTV within its limit.')
    return dict(catalogue_version=1, lender_id=institution.id, lender_name=institution.name,
                offer=offer.model_dump(mode='json'), ltv_percent=command.ltv_percent,
                term_months=command.term_months, unit_value_minor=command.unit_value_minor, simulated=True)
