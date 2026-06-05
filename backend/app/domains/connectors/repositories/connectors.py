from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.domains.connectors.schemas.connectors import (
    NormalizedExternalItem,
    ProviderRegistration,
)
from app.models.connector import (
    ConnectorConnection,
    ConnectorProvider,
    ExternalItem,
    ExternalSource,
)
from app.models.connector_credential import ConnectorCredential, ConnectorOAuthState
from app.models.connector_source import (
    ExternalItemTombstone,
    SourceDocument,
    SourceReference,
)
from app.models.connector_sync import ConnectorSyncJob, ConnectorSyncRun
from app.models.enums import ConnectorConnectionStatus, ConnectorSyncJobStatus


class ConnectorRepository:
    async def get_provider_by_key(
        self,
        session: AsyncSession,
        *,
        provider_key: str,
    ) -> ConnectorProvider | None:
        result = await session.execute(
            select(ConnectorProvider).where(ConnectorProvider.key == provider_key.strip().lower())
        )
        return result.scalar_one_or_none()

    async def upsert_provider(
        self,
        session: AsyncSession,
        *,
        registration: ProviderRegistration,
    ) -> ConnectorProvider:
        provider = await self.get_provider_by_key(session, provider_key=registration.key)
        capabilities = sorted(
            capability.value for capability in registration.capabilities.capabilities
        )
        rate_limits = [
            rate_limit.model_dump(mode="json")
            for rate_limit in registration.capabilities.rate_limits
        ]
        export_formats = [
            export_format.model_dump(mode="json")
            for export_format in registration.capabilities.export_formats
        ]
        if provider is not None:
            provider.display_name = registration.display_name
            provider.auth_type = registration.capabilities.auth_type.value
            provider.capabilities_json = capabilities
            provider.config_schema_json = registration.config_schema
            provider.rate_limits_json = rate_limits
            provider.export_formats_json = export_formats
            provider.is_enabled = registration.enabled_by_default
            await session.flush()
            await session.refresh(provider)
            return provider

        provider = ConnectorProvider(
            key=registration.key,
            display_name=registration.display_name,
            auth_type=registration.capabilities.auth_type.value,
            capabilities_json=capabilities,
            config_schema_json=registration.config_schema,
            rate_limits_json=rate_limits,
            export_formats_json=export_formats,
            is_enabled=registration.enabled_by_default,
        )
        session.add(provider)
        await session.flush()
        await session.refresh(provider)
        return provider

    async def create_connection(
        self,
        session: AsyncSession,
        *,
        organization_id: UUID,
        provider_id: UUID,
        display_name: str,
        collection_id: UUID | None = None,
        created_by_user_id: UUID | None = None,
        external_account_id: str | None = None,
        auth_config: dict | None = None,
    ) -> ConnectorConnection:
        connection = ConnectorConnection(
            organization_id=organization_id,
            provider_id=provider_id,
            collection_id=collection_id,
            created_by_user_id=created_by_user_id,
            external_account_id=external_account_id,
            display_name=display_name.strip(),
            status=ConnectorConnectionStatus.active.value,
            auth_config_json=auth_config or {},
        )
        session.add(connection)
        await session.flush()
        await session.refresh(connection)
        return connection

    async def get_connection(
        self,
        session: AsyncSession,
        *,
        organization_id: UUID,
        connection_id: UUID,
    ) -> ConnectorConnection | None:
        result = await session.execute(
            select(ConnectorConnection)
            .options(selectinload(ConnectorConnection.provider))
            .where(
                ConnectorConnection.id == connection_id,
                ConnectorConnection.organization_id == organization_id,
            )
        )
        return result.scalar_one_or_none()

    async def update_connection_auth_metadata(
        self,
        session: AsyncSession,
        *,
        connection: ConnectorConnection,
        auth_config: dict,
        status: ConnectorConnectionStatus | None = None,
        error_message: str | None = None,
    ) -> ConnectorConnection:
        connection.auth_config_json = auth_config
        if status is not None:
            connection.status = status.value
        connection.error_message = error_message
        await session.flush()
        await session.refresh(connection)
        return connection

    async def create_oauth_state(
        self,
        session: AsyncSession,
        *,
        organization_id: UUID,
        provider_key: str,
        state_hash: str,
        redirect_uri: str,
        requested_scopes: list[str],
        expires_at: datetime,
        created_by_user_id: UUID | None = None,
        connection_id: UUID | None = None,
        collection_id: UUID | None = None,
        display_name: str | None = None,
        external_account_id: str | None = None,
        config: dict | None = None,
    ) -> ConnectorOAuthState:
        state = ConnectorOAuthState(
            organization_id=organization_id,
            provider_key=provider_key,
            state_hash=state_hash,
            created_by_user_id=created_by_user_id,
            connection_id=connection_id,
            collection_id=collection_id,
            redirect_uri=redirect_uri,
            display_name=display_name,
            external_account_id=external_account_id,
            requested_scopes_json=requested_scopes,
            config_json=config or {},
            expires_at=expires_at,
        )
        session.add(state)
        await session.flush()
        await session.refresh(state)
        return state

    async def get_oauth_state_by_hash(
        self,
        session: AsyncSession,
        *,
        organization_id: UUID,
        state_hash: str,
    ) -> ConnectorOAuthState | None:
        result = await session.execute(
            select(ConnectorOAuthState).where(
                ConnectorOAuthState.organization_id == organization_id,
                ConnectorOAuthState.state_hash == state_hash,
            )
        )
        return result.scalar_one_or_none()

    async def consume_oauth_state(
        self,
        session: AsyncSession,
        *,
        state: ConnectorOAuthState,
        consumed_at: datetime,
        failure_reason: str | None = None,
    ) -> ConnectorOAuthState:
        state.consumed_at = consumed_at
        state.failure_reason = failure_reason
        await session.flush()
        await session.refresh(state)
        return state

    async def create_credential_version(
        self,
        session: AsyncSession,
        *,
        organization_id: UUID,
        connection_id: UUID,
        auth_type: str,
        encrypted_payload: str,
        encryption_key_id: str,
        encryption_algorithm: str,
        secret_fingerprint: str,
        scopes: list[str],
        metadata: dict,
        issued_at: datetime | None = None,
        expires_at: datetime | None = None,
        last_refreshed_at: datetime | None = None,
    ) -> ConnectorCredential:
        await session.execute(
            update(ConnectorCredential)
            .where(
                ConnectorCredential.organization_id == organization_id,
                ConnectorCredential.connection_id == connection_id,
                ConnectorCredential.is_current.is_(True),
            )
            .values(is_current=False)
        )
        version_result = await session.execute(
            select(func.max(ConnectorCredential.version)).where(
                ConnectorCredential.organization_id == organization_id,
                ConnectorCredential.connection_id == connection_id,
            )
        )
        next_version = (version_result.scalar_one_or_none() or 0) + 1
        credential = ConnectorCredential(
            organization_id=organization_id,
            connection_id=connection_id,
            auth_type=auth_type,
            encrypted_payload=encrypted_payload,
            encryption_key_id=encryption_key_id,
            encryption_algorithm=encryption_algorithm,
            secret_fingerprint=secret_fingerprint,
            scopes_json=scopes,
            metadata_json=metadata,
            issued_at=issued_at,
            expires_at=expires_at,
            last_refreshed_at=last_refreshed_at,
            version=next_version,
            is_current=True,
        )
        session.add(credential)
        await session.flush()
        await session.refresh(credential)
        return credential

    async def get_current_credential(
        self,
        session: AsyncSession,
        *,
        organization_id: UUID,
        connection_id: UUID,
    ) -> ConnectorCredential | None:
        result = await session.execute(
            select(ConnectorCredential).where(
                ConnectorCredential.organization_id == organization_id,
                ConnectorCredential.connection_id == connection_id,
                ConnectorCredential.is_current.is_(True),
            )
        )
        return result.scalar_one_or_none()

    async def mark_credential_status(
        self,
        session: AsyncSession,
        *,
        credential: ConnectorCredential,
        status: str,
        error_message: str | None = None,
        revoked_at: datetime | None = None,
        last_used_at: datetime | None = None,
    ) -> ConnectorCredential:
        credential.status = status
        credential.error_message = error_message
        if revoked_at is not None:
            credential.revoked_at = revoked_at
        if last_used_at is not None:
            credential.last_used_at = last_used_at
        await session.flush()
        await session.refresh(credential)
        return credential

    async def disable_sync_jobs_for_connection(
        self,
        session: AsyncSession,
        *,
        organization_id: UUID,
        connection_id: UUID,
    ) -> int:
        result = await session.execute(
            update(ConnectorSyncJob)
            .where(
                ConnectorSyncJob.organization_id == organization_id,
                ConnectorSyncJob.connection_id == connection_id,
                ConnectorSyncJob.status == ConnectorSyncJobStatus.active.value,
            )
            .values(status=ConnectorSyncJobStatus.disabled.value)
        )
        return int(getattr(result, "rowcount", 0) or 0)

    async def create_external_source(
        self,
        session: AsyncSession,
        *,
        organization_id: UUID,
        connection_id: UUID,
        provider_source_id: str,
        source_type: str,
        name: str,
        collection_id: UUID | None = None,
        source_url: str | None = None,
        config: dict | None = None,
        permissions: dict | None = None,
    ) -> ExternalSource:
        source = ExternalSource(
            organization_id=organization_id,
            connection_id=connection_id,
            collection_id=collection_id,
            provider_source_id=provider_source_id.strip(),
            source_type=source_type.strip(),
            name=name.strip(),
            source_url=source_url,
            config_json=config or {},
            permissions_json=permissions or {},
        )
        session.add(source)
        await session.flush()
        await session.refresh(source)
        return source

    async def get_external_source(
        self,
        session: AsyncSession,
        *,
        organization_id: UUID,
        external_source_id: UUID,
    ) -> ExternalSource | None:
        result = await session.execute(
            select(ExternalSource).where(
                ExternalSource.id == external_source_id,
                ExternalSource.organization_id == organization_id,
            )
        )
        return result.scalar_one_or_none()

    async def upsert_external_item(
        self,
        session: AsyncSession,
        *,
        item: NormalizedExternalItem,
    ) -> ExternalItem:
        if item.connection_id is None:
            raise ValueError("connection_id is required for external item persistence")
        result = await session.execute(
            select(ExternalItem).where(
                ExternalItem.organization_id == item.organization_id,
                ExternalItem.connection_id == item.connection_id,
                ExternalItem.provider_item_id == item.provider_item_id,
            )
        )
        external_item = result.scalar_one_or_none()
        if external_item is None:
            external_item = ExternalItem(
                organization_id=item.organization_id,
                connection_id=item.connection_id,
                external_source_id=item.external_source_id,
                collection_id=item.collection_id,
                provider_item_id=item.provider_item_id,
                provider_parent_id=item.provider_parent_id,
                root_provider_item_id=item.root_provider_item_id,
                item_type=item.item_type.value,
                title=item.title,
                source_url=item.source_url,
                content_hash=item.content_hash,
                source_updated_at=item.updated_at,
                sync_version=item.sync_version,
                mime_type=item.mime_type,
                visibility=item.visibility.value,
                acl_hash=item.acl_hash,
                metadata_json=item.metadata,
                permissions_json=item.permissions,
            )
            session.add(external_item)
        else:
            external_item.external_source_id = item.external_source_id
            external_item.collection_id = item.collection_id
            external_item.provider_parent_id = item.provider_parent_id
            external_item.root_provider_item_id = item.root_provider_item_id
            external_item.item_type = item.item_type.value
            external_item.title = item.title
            external_item.source_url = item.source_url
            external_item.content_hash = item.content_hash
            external_item.source_updated_at = item.updated_at
            external_item.sync_version = item.sync_version
            external_item.mime_type = item.mime_type
            external_item.visibility = item.visibility.value
            external_item.acl_hash = item.acl_hash
            external_item.metadata_json = item.metadata
            external_item.permissions_json = item.permissions
            external_item.deleted_at = None
        await session.flush()
        await session.refresh(external_item)
        return external_item

    async def get_external_item(
        self,
        session: AsyncSession,
        *,
        organization_id: UUID,
        external_item_id: UUID,
    ) -> ExternalItem | None:
        result = await session.execute(
            select(ExternalItem).where(
                ExternalItem.id == external_item_id,
                ExternalItem.organization_id == organization_id,
            )
        )
        return result.scalar_one_or_none()

    async def create_sync_job(
        self,
        session: AsyncSession,
        *,
        organization_id: UUID,
        connection_id: UUID,
        name: str,
        external_source_id: UUID | None = None,
        collection_id: UUID | None = None,
        schedule: dict | None = None,
    ) -> ConnectorSyncJob:
        sync_job = ConnectorSyncJob(
            organization_id=organization_id,
            connection_id=connection_id,
            external_source_id=external_source_id,
            collection_id=collection_id,
            name=name.strip(),
            status=ConnectorSyncJobStatus.active.value,
            schedule_json=schedule or {},
        )
        session.add(sync_job)
        await session.flush()
        await session.refresh(sync_job)
        return sync_job

    async def create_sync_run(
        self,
        session: AsyncSession,
        *,
        organization_id: UUID,
        sync_job_id: UUID,
        connection_id: UUID,
        sync_version: int,
        external_source_id: UUID | None = None,
        status: str = "queued",
        cursor_before: dict | None = None,
    ) -> ConnectorSyncRun:
        sync_run = ConnectorSyncRun(
            organization_id=organization_id,
            sync_job_id=sync_job_id,
            connection_id=connection_id,
            external_source_id=external_source_id,
            status=status,
            sync_version=sync_version,
            cursor_before_json=cursor_before or {},
        )
        session.add(sync_run)
        await session.flush()
        await session.refresh(sync_run)
        return sync_run

    async def update_sync_run_result(
        self,
        session: AsyncSession,
        *,
        sync_run: ConnectorSyncRun,
        status: str,
        completed_at: datetime,
        items_seen: int,
        items_upserted: int,
        items_deleted: int,
        cursor_after: dict | None = None,
        error_message: str | None = None,
        error_details: dict | None = None,
    ) -> ConnectorSyncRun:
        sync_run.status = status
        sync_run.completed_at = completed_at
        sync_run.items_seen = items_seen
        sync_run.items_upserted = items_upserted
        sync_run.items_deleted = items_deleted
        sync_run.cursor_after_json = cursor_after or {}
        sync_run.error_message = error_message
        sync_run.error_details_json = error_details or {}
        await session.flush()
        await session.refresh(sync_run)
        return sync_run

    async def link_source_document(
        self,
        session: AsyncSession,
        *,
        organization_id: UUID,
        external_item_id: UUID,
        document_id: UUID,
        content_hash: str,
        sync_version: int,
        collection_id: UUID | None = None,
        sync_run_id: UUID | None = None,
    ) -> SourceDocument:
        source_document = SourceDocument(
            organization_id=organization_id,
            external_item_id=external_item_id,
            document_id=document_id,
            collection_id=collection_id,
            sync_run_id=sync_run_id,
            content_hash=content_hash,
            sync_version=sync_version,
        )
        session.add(source_document)
        await session.flush()
        await session.refresh(source_document)
        return source_document

    async def create_source_reference(
        self,
        session: AsyncSession,
        *,
        organization_id: UUID,
        source_document_id: UUID,
        external_item_id: UUID,
        document_id: UUID,
        reference_type: str,
        source_url: str,
        chunk_id: UUID | None = None,
        title: str | None = None,
        locator: dict | None = None,
        metadata: dict | None = None,
    ) -> SourceReference:
        reference = SourceReference(
            organization_id=organization_id,
            source_document_id=source_document_id,
            external_item_id=external_item_id,
            document_id=document_id,
            chunk_id=chunk_id,
            reference_type=reference_type,
            source_url=source_url,
            title=title,
            locator_json=locator or {},
            metadata_json=metadata or {},
        )
        session.add(reference)
        await session.flush()
        await session.refresh(reference)
        return reference

    async def record_tombstone(
        self,
        session: AsyncSession,
        *,
        organization_id: UUID,
        connection_id: UUID,
        provider_item_id: str,
        tombstoned_at: datetime,
        external_source_id: UUID | None = None,
        sync_run_id: UUID | None = None,
        item_type: str | None = None,
        source_url: str | None = None,
        last_seen_sync_version: int | None = None,
        reason: str | None = None,
        metadata: dict | None = None,
    ) -> ExternalItemTombstone:
        tombstone = ExternalItemTombstone(
            organization_id=organization_id,
            connection_id=connection_id,
            external_source_id=external_source_id,
            sync_run_id=sync_run_id,
            provider_item_id=provider_item_id,
            item_type=item_type,
            source_url=source_url,
            tombstoned_at=tombstoned_at,
            last_seen_sync_version=last_seen_sync_version,
            reason=reason,
            metadata_json=metadata or {},
        )
        session.add(tombstone)
        await session.flush()
        await session.refresh(tombstone)
        return tombstone
