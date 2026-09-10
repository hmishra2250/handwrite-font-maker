"""Explicit alpha entitlements and a fail-closed future checkout boundary.

No purchase ledger or provider events are fabricated. Alpha access is granted by
operator provisioning, not by a client-selected plan or a success redirect.
"""
from .security import AuthContext, RuntimeConfig, SecurityError

OFFERS = (
    {'id': 'single', 'name': 'Make one font', 'priceCents': 1200, 'projects': 1},
    {'id': 'three_pack', 'name': 'Make three fonts', 'priceCents': 2900, 'projects': 3},
)


def catalog():
    return {
        'currency': 'USD', 'billingEnabled': False,
        'offers': [dict(offer) for offer in OFFERS],
        'alpha': {'name': 'Private alpha', 'priceCents': 0, 'inviteOnly': True},
        'notice': 'Private alpha is free for invited accounts. Paid offers are planned, not available to purchase. No card is collected.',
    }


def account(config: RuntimeConfig, auth: AuthContext):
    return {
        'user': {'id': auth.owner_id, 'email': auth.email},
        'plan': {'id': 'private_alpha', 'name': 'Private alpha', 'billingEnabled': False},
        'limits': {
            'dailyUploads': config.daily_upload_limit,
            'dailyUploadBytes': config.daily_upload_bytes_limit,
            'dailyPreviews': config.daily_preview_limit,
            'dailyBuilds': config.daily_build_limit,
            'activeJobs': config.active_job_limit,
        },
        'retention': {'projectDays': 7, 'downloadHours': 24},
    }


def checkout(offer_id: object):
    if not isinstance(offer_id, str) or offer_id not in {offer['id'] for offer in OFFERS}:
        raise SecurityError(400, 'OFFER_INVALID', 'Choose a recognized offer.')
    raise SecurityError(503, 'PAYMENT_NOT_CONFIGURED', 'Payments are not enabled. Invited accounts can use the free private alpha; no charge was made.')
