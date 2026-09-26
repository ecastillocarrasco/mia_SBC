from __future__ import annotations

from mia.data import Database
from mia.settings import Settings
from mia.sources import Pseudonymizer
from mia.sources.sharepoint import CertificateTokenProvider, SharePointClient
from mia.sync.runner import SyncRunner


def build_sharepoint_client(settings: Settings) -> SharePointClient:
    sp = settings.sharepoint
    if not sp.configured:
        raise ValueError(
            "SharePoint no está configurado: revisa MIA_SHAREPOINT__TENANT_ID, CLIENT_ID, CERT_THUMBPRINT, "
            "RRHH_SITE_URL y el certificado (CERT_PFX_PATH o CERT_PFX_BASE64)."
        )
    return SharePointClient(
        site_url=sp.rrhh_site_url,
        tokens=CertificateTokenProvider(sp),
        timeout_seconds=sp.timeout_seconds,
        page_size=sp.page_size,
        max_retries=sp.max_retries,
        concurrency=sp.concurrency,
    )


def build_runner(settings: Settings, db: Database, client: SharePointClient) -> SyncRunner:
    return SyncRunner(
        db=db,
        client=client,
        pseudonymize=Pseudonymizer(settings.data.pseudonym_key.get_secret_value()),
        timezone=settings.timezone,
        full_sync_hour=settings.data.full_sync_hour,
    )
