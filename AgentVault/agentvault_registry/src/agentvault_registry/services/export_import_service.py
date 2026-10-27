"""
Export/Import Service for Agent Configuration Portability
Implements secure agent configuration export and import with validation
"""

import json
import hashlib
import logging
import secrets
from datetime import datetime, timezone
from typing import Dict, Any, Optional, List, Tuple
import uuid
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, text

from agentvault_registry.models import (
    Agent, AgentCard, Developer,
    AgentCapability, AgentEndpoint, AgentVersion,
    AgentMetrics, AgentTag  # Changed from AgentMetric to AgentMetrics
)
from agentvault_registry.event_emitter import EventEmitter
from agentvault_registry.config import settings
from agentvault_registry.identifiers import generate_local_agent_did

logger = logging.getLogger(__name__)


class ExportImportService:
    """Service for handling agent export and import operations"""
    
    # Export format version for future compatibility
    EXPORT_VERSION = "1.0.0"
    
    # Fields to exclude from export for security
    SENSITIVE_FIELDS = {
        'api_key', 'api_secret', 'private_key', 'password',
        'token', 'credential', 'secret', 'auth_token',
        'service_account_json', 'encryption_key'
    }
    
    def __init__(self):
        """Initialize the service with Event Store emitter"""
        self.event_emitter = EventEmitter(
            event_store_url=getattr(settings, 'EVENT_STORE_URL', "http://localhost:8200"),
            internal_api_key=getattr(settings, 'EVENT_STORE_API_KEY', ""),
            source_service="registry"
        )
    
    async def export_agent(
        self,
        agent_did: str,
        developer_id: int,
        db: AsyncSession,
        include_metrics: bool = False,
        include_versions: bool = True
    ) -> Dict[str, Any]:
        """
        Export agent configuration to portable format
        
        Args:
            agent_did: Agent DID to export
            developer_id: Developer requesting export (for ownership check)
            db: Database session
            include_metrics: Whether to include performance metrics
            include_versions: Whether to include version history
            
        Returns:
            Exportable agent configuration dictionary
        """
        
        # Get agent with ownership verification
        stmt = select(Agent).where(
            and_(
                Agent.did == agent_did,
                Agent.creator_developer_id == developer_id
            )
        )
        result = await db.execute(stmt)
        agent = result.scalar_one_or_none()
        
        if not agent:
            raise ValueError(f"Agent {agent_did} not found or access denied")
        
        # Build export package
        # §pass51 Phase 1 triage (2026-05-20): added metadata.audit block as
        # read-only home for economic state. These fields are NEVER restored
        # on import; they exist purely so a 6-months-later inspection of the
        # bundle can verify what state the agent was in at export time.
        # Cast to float at the boundary to dodge Decimal -> JSON serialization
        # crash that took out the entire feature pre-§pass51.
        def _to_float(val):
            if val is None:
                return 0.0
            try:
                return float(val)
            except (TypeError, ValueError):
                return 0.0

        export_data = {
            "export_version": self.EXPORT_VERSION,
            "export_timestamp": datetime.now(timezone.utc).isoformat(),
            "export_id": str(uuid.uuid4()),
            "agent": await self._export_agent_core(agent, db),
            "metadata": {
                "original_did": agent.did,
                "original_created_at": agent.created_at.isoformat() if agent.created_at else None,
                "original_developer_id": developer_id,
                "export_checksum": None,  # Will be calculated at the end
                "audit": {
                    "economic_state_snapshot_at_export": {
                        "liquid_balance": _to_float(agent.liquid_balance),
                        "staked_balance": _to_float(agent.staked_balance),
                        "reputation_score": _to_float(agent.reputation_score),
                        "note": "READ-ONLY. Not restored on import. For audit/forensics only."
                    }
                }
            }
        }
        
        # Add optional components
        if include_versions:
            export_data["versions"] = await self._export_agent_versions(agent.did, db)
        
        if include_metrics:
            export_data["metrics"] = await self._export_agent_metrics(agent.did, db)
        
        # Get agent card if exists
        agent_card = await self._get_agent_card(agent.did, db)
        if agent_card:
            export_data["agent_card"] = await self._export_agent_card(agent_card)
        
        # Get capabilities
        capabilities = await self._get_agent_capabilities(agent.did, db)
        if capabilities:
            export_data["capabilities"] = [
                self._sanitize_capability(cap) for cap in capabilities
            ]
        
        # Get endpoints
        endpoints = await self._get_agent_endpoints(agent.did, db)
        if endpoints:
            export_data["endpoints"] = [
                self._sanitize_endpoint(ep) for ep in endpoints
            ]
        
        # Get tags
        tags = await self._get_agent_tags(agent.did, db)
        if tags:
            export_data["tags"] = tags
        
        # Calculate checksum for integrity verification
        export_data["metadata"]["export_checksum"] = self._calculate_checksum(export_data)
        
        # Log export event
        await self._log_export_event(agent.did, developer_id, export_data["export_id"], db)
        
        return export_data
    
    async def import_agent(
        self,
        import_data: Dict[str, Any],
        developer_id: int,
        db: AsyncSession,
        conflict_resolution: str = "skip",  # "skip", "rename", "overwrite"
        dry_run: bool = False
    ) -> Tuple[Optional[Agent], Dict[str, Any]]:
        """
        Import agent from exported configuration
        
        Args:
            import_data: Exported agent data
            developer_id: Developer importing the agent
            db: Database session
            conflict_resolution: How to handle DID conflicts
            dry_run: If True, validate but don't actually import
            
        Returns:
            Tuple of (imported Agent or None, import report)
        """
        
        report = {
            "success": False,
            "agent_did": None,
            "warnings": [],
            "errors": [],
            "statistics": {
                "capabilities_imported": 0,
                "endpoints_imported": 0,
                "tags_imported": 0,
                "versions_imported": 0
            }
        }
        
        try:
            # Validate export format
            validation_errors = self._validate_import_data(import_data)
            if validation_errors:
                report["errors"] = validation_errors
                return None, report
            
            # Check version compatibility
            if not self._is_version_compatible(import_data.get("export_version")):
                report["errors"].append(f"Incompatible export version: {import_data.get('export_version')}")
                return None, report
            
            # Verify checksum
            if not self._verify_checksum(import_data):
                report["warnings"].append("Checksum verification failed - data may be corrupted")
            
            agent_data = import_data["agent"]
            original_did = import_data["metadata"]["original_did"]
            
            # The actual DID we're trying to import (might be different from original if renamed)
            import_did = agent_data.get("did", original_did)
            logger.info(f"Import: Attempting to import agent with DID {import_did} (original: {original_did})")
            
            # Handle DID conflicts - check the actual DID being imported, not the original
            existing = await self._check_agent_exists(import_did, db)
            if existing:
                logger.warning(f"Import: Agent {import_did} already exists in database")
                if conflict_resolution == "skip":
                    report["errors"].append(f"Agent {import_did} already exists")
                    return None, report
                elif conflict_resolution == "rename":
                    # Generate new DID
                    agent_data["did"] = self._generate_new_did(import_did)
                    report["warnings"].append(f"Agent renamed from {import_did} to {agent_data['did']}")
                elif conflict_resolution == "overwrite":
                    # Delete existing agent (if owned by same developer)
                    if existing.creator_developer_id != developer_id:
                        report["errors"].append(f"Cannot overwrite agent owned by another developer")
                        return None, report
                    if not dry_run:
                        await self._delete_agent_cascade(existing.did, db)
                    report["warnings"].append(f"Overwriting existing agent {original_did}")
            
            # ALWAYS generate new client_id and secret for imported/cloned agents
            new_client_id = f"agent_{str(uuid.uuid4())[:8]}"
            new_client_secret = secrets.token_urlsafe(32)
            
            if dry_run:
                report["success"] = True
                report["agent_did"] = agent_data["did"]
                report["warnings"].append("Dry run - no data was actually imported")
                report["new_credentials"] = {
                    "client_id": new_client_id,
                    "note": "These would be the new credentials (dry run)"
                }
                return None, report
            
            # Create agent
            
            # Hash the client secret
            from agentvault_registry.security import hash_password
            hashed_secret = hash_password(new_client_secret)
            
            # §pass51 Phase 1 triage (2026-05-20):
            # Economic state (reputation_score, liquid_balance, staked_balance)
            # is EXPLICITLY IGNORED even if present in legacy .json exports.
            # Importing balance from an export would let a federated registry
            # mint AVT out of thin air (supply-invariant violation). New agents
            # ALWAYS start fresh: reputation=100, balances=0. The export's
            # audit block (metadata.audit.economic_state_snapshot_at_export)
            # is read-only and never read by the import path.
            agent = Agent(
                did=agent_data["did"],
                client_id=new_client_id,  # ALWAYS use new client_id to avoid duplicates
                hashed_client_secret=hashed_secret,  # New secret for security
                creator_developer_id=developer_id,
                public_key_jwk=agent_data.get("public_key_jwk"),
                status=agent_data.get("status", "active"),
                reputation_score=100,   # never honor legacy export's value
                liquid_balance=0,        # never honor legacy export's value
                staked_balance=0,        # never honor legacy export's value
                created_at=datetime.now(timezone.utc),
                last_active_at=None
            )
            
            db.add(agent)
            await db.flush()  # Get the agent ID
            
            # Import agent card if present, or create one from agent data.
            # NOTE: the ExportResponse model materializes every optional component as JSON
            # `null` when empty, so a clean export→import round-trip sends `agent_card: null`
            # (and null capabilities/endpoints/tags/versions). Guard on TRUTHINESS, not mere
            # key-presence, or `_import_agent_card(None)` / `for x in None` crash the import.
            if import_data.get("agent_card"):
                await self._import_agent_card(
                    agent.did,
                    import_data["agent_card"],
                    developer_id,
                    db
                )
            else:
                # Create a basic agent card with the name from agent data
                agent_card_data = {
                    "name": agent_data.get("name", "Imported Agent"),
                    "description": "",
                    "is_public": True
                }
                await self._import_agent_card(
                    agent.did,
                    agent_card_data,
                    developer_id,
                    db
                )
            
            # Import capabilities · endpoints · tags · versions. `.get(...) or []` so a
            # round-tripped export (whose empty components serialize as null) is a clean
            # no-op instead of a 'NoneType' object is not iterable crash.
            for cap in (import_data.get("capabilities") or []):
                await self._import_capability(agent.did, cap, db)
                report["statistics"]["capabilities_imported"] += 1

            for endpoint in (import_data.get("endpoints") or []):
                await self._import_endpoint(agent.did, endpoint, db)
                report["statistics"]["endpoints_imported"] += 1

            for tag in (import_data.get("tags") or []):
                await self._import_tag(agent.did, tag, db)
                report["statistics"]["tags_imported"] += 1

            for version in (import_data.get("versions") or []):
                await self._import_version(agent.did, version, db)
                report["statistics"]["versions_imported"] += 1
            
            # Commit transaction
            await db.commit()
            
            # Log import event
            await self._log_import_event(
                agent.did,
                developer_id,
                import_data.get("export_id"),
                original_did,
                db
            )
            
            report["success"] = True
            report["agent_did"] = agent.did
            # Include the new credentials in the report for the user
            report["new_credentials"] = {
                "client_id": new_client_id,
                "client_secret": new_client_secret,  # Only shown once, on creation
                "note": "Save these credentials securely - the secret cannot be retrieved again"
            }
            
            return agent, report
            
        except Exception as e:
            await db.rollback()
            report["errors"].append(f"Import failed: {str(e)}")
            return None, report
    
    # ===== EXPORT HELPER METHODS =====
    
    async def _export_agent_core(self, agent: Agent, db: AsyncSession) -> Dict[str, Any]:
        """Export core agent data, excluding sensitive fields"""
        # Get agent card for this developer that might be related to this agent
        # Since AgentCard doesn't have direct link to Agent, we search by developer_id
        # and try to match by DID in card_data
        agent_card_stmt = select(AgentCard).where(
            AgentCard.developer_id == agent.creator_developer_id
        )
        agent_card_result = await db.execute(agent_card_stmt)
        agent_cards = agent_card_result.scalars().all()
        
        # Try to find the matching agent card by checking card_data for DID
        agent_card = None
        agent_name = "Unnamed Agent"
        for card in agent_cards:
            if card.card_data and isinstance(card.card_data, dict):
                # Check if this card is for our agent
                card_did = card.card_data.get('did') or card.card_data.get('humanReadableId')
                if card_did == agent.did:
                    agent_card = card
                    agent_name = card.name
                    break
        
        # If no matching card found, try to use the first card's name as fallback
        if not agent_card and agent_cards:
            agent_name = agent_cards[0].name if agent_cards[0].name else "Unnamed Agent"
        
        # §pass51 Phase 1 triage (2026-05-20):
        # - Removed client_id (regenerated on import, useless export field)
        # - Removed creator_developer_id (redundant w/ metadata.original_developer_id)
        # - Removed liquid_balance, staked_balance, reputation_score (Decimal
        #   serialization bug AND federation-mint attack vector — these fields
        #   are economic state, not config; moved to metadata.audit block as
        #   read-only audit. Never restored.)
        agent_dict = {
            "did": agent.did,
            "name": agent_name,
            "status": agent.status,
            "public_key_jwk": agent.public_key_jwk,
        }

        return agent_dict
    
    async def _export_agent_card(self, agent_card: AgentCard) -> Dict[str, Any]:
        """Export agent card data"""
        # Extract data from card_data JSON if available
        card_data = agent_card.card_data if agent_card.card_data else {}
        
        return {
            "name": agent_card.name if agent_card.name else "Agent",
            "description": agent_card.description if agent_card.description else "",
            "is_public": True,  # Default to public
            "tags": card_data.get('tags', []),
            "website": card_data.get('website'),
            "logo_url": card_data.get('logo_url')
        }
    
    async def _export_agent_versions(self, agent_did: str, db: AsyncSession) -> List[Dict[str, Any]]:
        """Export agent version history"""
        stmt = select(AgentVersion).where(
            AgentVersion.agent_did == agent_did
        ).order_by(AgentVersion.created_at.desc()).limit(10)  # Last 10 versions
        
        result = await db.execute(stmt)
        versions = result.scalars().all()
        
        return [
            {
                "version": v.version,
                "changelog": v.changelog,
                "configuration": self._sanitize_configuration(v.configuration),
                "created_at": v.created_at.isoformat() if v.created_at else None
            }
            for v in versions
        ]
    
    async def _export_agent_metrics(self, agent_did: str, db: AsyncSession) -> Dict[str, Any]:
        """Export agent performance metrics"""
        # Note: AgentMetrics uses agent_id, not agent_did, so we need to get the agent first
        agent_stmt = select(Agent).where(Agent.did == agent_did)
        agent_result = await db.execute(agent_stmt)
        agent = agent_result.scalar_one_or_none()
        
        if not agent:
            return {}
        
        stmt = select(AgentMetrics).where(
            AgentMetrics.agent_id == agent.id
        )
        
        result = await db.execute(stmt)
        metrics = result.scalar_one_or_none()
        
        if not metrics:
            return {}
        
        # AgentMetrics is a single aggregated record, not multiple records
        return {
            "total_requests": metrics.total_requests,
            "successful_requests": metrics.successful_requests,
            "failed_requests": metrics.failed_requests,
            "avg_response_time": metrics.avg_response_time if hasattr(metrics, 'avg_response_time') else metrics.total_response_time_ms / max(metrics.successful_requests, 1),
            "success_rate": metrics.success_rate,
            "last_request_at": metrics.last_request_at.isoformat() if metrics.last_request_at else None
        }
    
    # ===== IMPORT HELPER METHODS =====
    
    async def _import_agent_card(
        self,
        agent_did: str,
        card_data: Dict[str, Any],
        developer_id: int,
        db: AsyncSession
    ):
        """Import agent card"""
        # Create card_data JSON with agent information
        import_card_data = {
            "did": agent_did,
            "humanReadableId": agent_did,
            "name": card_data.get("name", "Imported Agent"),
            "description": card_data.get("description", ""),
            "tags": card_data.get("tags", []),
            "website": card_data.get("website"),
            "logo_url": card_data.get("logo_url")
        }
        
        # §MCPTEST30 (2026-10-01): the card is LINKED to its agent. It carried the DID only inside its JSON, so every
        # reader that joins on agent_cards.agent_did (discovery, the card rails, an agent's deletion) saw an agent
        # with no card, and deleting the agent left its card active (sandbox: 296 such cards, 85 for revoked agents).
        # An overwrite hard-deletes the old agent but not its card (no foreign key), and agent_did is unique, so the
        # card that survived is updated rather than joined by a second.
        now = datetime.now(timezone.utc)
        existing = await self._linked_card(agent_did, db)
        if existing is not None:
            existing.card_data = import_card_data
            existing.name = card_data.get("name", "Imported Agent")
            existing.description = card_data.get("description", "")
            existing.developer_id = developer_id
            existing.is_active = True
            existing.updated_at = now
            return
        agent_card = AgentCard(
            id=uuid.uuid4(),  # Generate UUID for the card
            agent_did=agent_did,
            developer_id=developer_id,
            card_data=import_card_data,  # Store agent info in JSON
            name=card_data.get("name", "Imported Agent"),
            description=card_data.get("description", ""),
            is_active=True,
            created_at=now,
            updated_at=now
        )
        db.add(agent_card)
    
    async def _import_capability(self, agent_did: str, cap_data: Dict[str, Any], db: AsyncSession):
        """Import agent capability"""
        capability = AgentCapability(
            agent_did=agent_did,
            name=cap_data["name"],
            description=cap_data.get("description"),
            category=cap_data.get("category"),
            version=cap_data.get("version"),
            parameters=cap_data.get("parameters", {}),
            is_active=cap_data.get("is_active", True)
        )
        db.add(capability)
    
    async def _import_endpoint(self, agent_did: str, endpoint_data: Dict[str, Any], db: AsyncSession):
        """Import agent endpoint"""
        endpoint = AgentEndpoint(
            agent_did=agent_did,
            path=endpoint_data["path"],
            method=endpoint_data["method"],
            description=endpoint_data.get("description"),
            parameters=endpoint_data.get("parameters", {}),
            response_schema=endpoint_data.get("response_schema", {}),
            is_active=endpoint_data.get("is_active", True)
        )
        db.add(endpoint)
    
    async def _import_tag(self, agent_did: str, tag: str, db: AsyncSession):
        """Import agent tag"""
        agent_tag = AgentTag(
            agent_did=agent_did,
            tag=tag
        )
        db.add(agent_tag)
    
    async def _import_version(self, agent_did: str, version_data: Dict[str, Any], db: AsyncSession):
        """Import agent version"""
        version = AgentVersion(
            agent_did=agent_did,
            version=version_data["version"],
            changelog=version_data.get("changelog"),
            configuration=version_data.get("configuration", {}),
            created_at=datetime.now(timezone.utc)
        )
        db.add(version)
    
    # ===== UTILITY METHODS =====
    
    def _sanitize_configuration(self, config: Optional[Dict]) -> Dict:
        """Remove sensitive fields from configuration"""
        if not config:
            return {}
        
        sanitized = {}
        for key, value in config.items():
            if not any(sensitive in key.lower() for sensitive in self.SENSITIVE_FIELDS):
                if isinstance(value, dict):
                    sanitized[key] = self._sanitize_configuration(value)
                else:
                    sanitized[key] = value
        return sanitized
    
    def _sanitize_metadata(self, metadata: Optional[Dict]) -> Dict:
        """Remove sensitive fields from metadata"""
        return self._sanitize_configuration(metadata)
    
    def _sanitize_capability(self, capability: AgentCapability) -> Dict[str, Any]:
        """Convert capability to sanitized dict"""
        return {
            "name": capability.name,
            "description": capability.description,
            "category": capability.category,
            "version": capability.version,
            "parameters": self._sanitize_configuration(capability.parameters),
            "is_active": capability.is_active
        }
    
    def _sanitize_endpoint(self, endpoint: AgentEndpoint) -> Dict[str, Any]:
        """Convert endpoint to sanitized dict"""
        return {
            "path": endpoint.path,
            "method": endpoint.method,
            "description": endpoint.description,
            "parameters": self._sanitize_configuration(endpoint.parameters),
            "response_schema": endpoint.response_schema,
            "is_active": endpoint.is_active
        }
    
    # Optional top-level components the ExportResponse model always materializes (as null
    # when empty). Absent, null, and empty MUST hash identically so a clean export→import
    # round-trip verifies — otherwise the API boundary (which fills them with null) always
    # trips the "data may be corrupted" warning even on untouched data.
    _CHECKSUM_OPTIONAL = ("agent_card", "capabilities", "endpoints", "tags", "versions", "metrics")

    def _canonical_for_checksum(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Normalize export data so integrity is invariant to the API's null-materialization
        of empty optional components (and to the checksum field itself)."""
        d = dict(data)
        md = d.get("metadata")
        if isinstance(md, dict):
            d["metadata"] = {k: v for k, v in md.items() if k != "export_checksum"}
        for k in self._CHECKSUM_OPTIONAL:
            v = d.get(k)
            if v is None or v == [] or v == {}:
                d.pop(k, None)
        return d

    def _calculate_checksum(self, data: Dict[str, Any]) -> str:
        """Calculate SHA256 checksum of export data (invariant to null-vs-absent optionals)."""
        json_str = json.dumps(self._canonical_for_checksum(data), sort_keys=True, default=str)
        return hashlib.sha256(json_str.encode()).hexdigest()
    
    def _verify_checksum(self, data: Dict[str, Any]) -> bool:
        """Verify export data checksum"""
        if "metadata" not in data or "export_checksum" not in data["metadata"]:
            return False
        
        stored_checksum = data["metadata"]["export_checksum"]
        calculated_checksum = self._calculate_checksum(data)
        return stored_checksum == calculated_checksum
    
    def _validate_import_data(self, data: Dict[str, Any]) -> List[str]:
        """Validate import data structure"""
        errors = []
        
        required_fields = ["export_version", "agent", "metadata"]
        for field in required_fields:
            if field not in data:
                errors.append(f"Missing required field: {field}")
        
        if "agent" in data:
            agent_required = ["did", "name"]
            for field in agent_required:
                if field not in data["agent"]:
                    errors.append(f"Missing required agent field: {field}")
        
        return errors
    
    def _is_version_compatible(self, version: str) -> bool:
        """Check if export version is compatible"""
        if not version:
            return False
        
        # Simple major version check
        export_major = version.split(".")[0]
        current_major = self.EXPORT_VERSION.split(".")[0]
        return export_major == current_major
    
    async def _check_agent_exists(self, did: str, db: AsyncSession) -> Optional[Agent]:
        """Check if agent already exists"""
        stmt = select(Agent).where(Agent.did == did)
        result = await db.execute(stmt)
        return result.scalar_one_or_none()
    
    def _generate_new_did(self, original_did: str) -> str:
        """Generate new DID for renamed agent"""
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
        return f"{original_did}_imported_{timestamp}"
    
    async def _delete_agent_cascade(self, did: str, db: AsyncSession):
        """Delete agent and all related data"""
        # Delete in order of dependencies
        tables = [
            AgentTag, AgentEndpoint, AgentCapability,
            AgentVersion, AgentMetrics, Agent  # Changed AgentMetric to AgentMetrics
        ]
        
        for table in tables:
            if table == Agent:
                # Direct delete for Agent table
                stmt = text("DELETE FROM agents WHERE did = :did")
            else:
                # For related tables, use agent_did foreign key
                stmt = text(f"DELETE FROM {table.__tablename__} WHERE agent_did = :did")
            await db.execute(stmt, {"did": did})
    
    async def _linked_card(self, agent_did: str, db: AsyncSession) -> Optional[AgentCard]:
        """The card whose agent_did column names this agent: the link every reader of a card joins on."""
        result = await db.execute(select(AgentCard).where(AgentCard.agent_did == agent_did))
        return result.scalars().first()

    async def _unlinked_cards_of(self, developer_id: int, db: AsyncSession) -> List[AgentCard]:
        """The developer's cards that name no agent in agent_did (imports made before §MCPTEST30 linked them)."""
        result = await db.execute(select(AgentCard).where(AgentCard.developer_id == developer_id,
                                                          AgentCard.agent_did.is_(None)))
        return list(result.scalars().all())

    async def _get_agent_card(self, agent_did: str, db: AsyncSession) -> Optional[AgentCard]:
        """THIS agent's card: the linked one, else an unlinked card of its developer whose JSON names this DID.

        §MCPTEST30 (2026-10-01): the lookup read only the developer's cards by the DID in their JSON, and with no match
        it returned the developer's FIRST card, so exporting (or cloning) an agent carried another agent's card. No
        card is better than a stranger's: the import then makes one from the agent's own name."""
        card = await self._linked_card(agent_did, db)
        if card is not None:
            return card
        agent = (await db.execute(select(Agent).where(Agent.did == agent_did))).scalar_one_or_none()
        if not agent:
            return None
        for card in await self._unlinked_cards_of(agent.creator_developer_id, db):
            if isinstance(card.card_data, dict):
                if (card.card_data.get('did') or card.card_data.get('humanReadableId')) == agent_did:
                    return card
        return None
    
    async def _get_agent_capabilities(self, agent_did: str, db: AsyncSession) -> List[AgentCapability]:
        """Get agent capabilities"""
        stmt = select(AgentCapability).where(AgentCapability.agent_did == agent_did)
        result = await db.execute(stmt)
        return result.scalars().all()
    
    async def _get_agent_endpoints(self, agent_did: str, db: AsyncSession) -> List[AgentEndpoint]:
        """Get agent endpoints"""
        stmt = select(AgentEndpoint).where(AgentEndpoint.agent_did == agent_did)
        result = await db.execute(stmt)
        return result.scalars().all()
    
    async def _get_agent_tags(self, agent_did: str, db: AsyncSession) -> List[str]:
        """Get agent tags"""
        stmt = select(AgentTag.tag).where(AgentTag.agent_did == agent_did)
        result = await db.execute(stmt)
        return result.scalars().all()
    
    async def _log_export_event(
        self,
        agent_did: str,
        developer_id: int,
        export_id: str,
        db: AsyncSession
    ):
        """Log agent export to event store"""
        try:
            await self.event_emitter.emit(
                event_type="AgentExported",
                aggregate_id=agent_did,
                aggregate_type="Agent",
                data={
                    "export_id": export_id,
                    "developer_id": developer_id,
                    "timestamp": datetime.now(timezone.utc).isoformat()
                },
                metadata={
                    "source_service": "registry",
                    "operation": "export"
                }
            )
        except Exception as e:
            logger.error(f"Failed to emit export event: {e}")
            # Don't fail the export if event emission fails
    
    async def _log_import_event(
        self,
        agent_did: str,
        developer_id: int,
        export_id: str,
        original_did: str,
        db: AsyncSession
    ):
        """Log agent import to event store"""
        try:
            await self.event_emitter.emit(
                event_type="AgentImported",
                aggregate_id=agent_did,
                aggregate_type="Agent",
                data={
                    "export_id": export_id,
                    "developer_id": developer_id,
                    "original_did": original_did,
                    "timestamp": datetime.now(timezone.utc).isoformat()
                },
                metadata={
                    "source_service": "registry",
                    "operation": "import"
                }
            )
        except Exception as e:
            logger.error(f"Failed to emit import event: {e}")
            # Don't fail the import if event emission fails
    
    async def clone_agent(
        self,
        agent_did: str,
        developer_id: int,
        db: AsyncSession,
        new_name: Optional[str] = None
    ) -> Tuple[Optional[Agent], Dict[str, Any]]:
        """
        Clone an existing agent to create a new copy.
        
        Args:
            agent_did: DID of the agent to clone
            developer_id: Developer performing the clone
            db: Database session
            new_name: Optional new name for the clone
            
        Returns:
            Tuple of (cloned Agent or None, clone report)
        """
        logger.info(f"Starting clone of agent {agent_did} for developer {developer_id}")
        
        # Export the agent
        export_data = await self.export_agent(
            agent_did=agent_did,
            developer_id=developer_id,
            db=db,
            include_metrics=False,  # Don't copy metrics
            include_versions=False  # Don't copy version history
        )
        
        # Modify the export for cloning
        # Generate a new DID for the clone to ensure uniqueness
        # A fresh DID from the ONE generator (§DIDWIDEN). The old fallback appended a
        # per-second timestamp to the SOURCE did, which collided by construction for two
        # clones in the same second; lineage lives in the metadata, not the identifier.
        new_did = generate_local_agent_did("cos" if agent_did.startswith("did:cos:") else "theprotocol")
        
        # Update both the agent data and metadata to reflect the new DID
        export_data["agent"]["did"] = new_did
        logger.info(f"Clone: Changed DID from {agent_did} to {new_did}")
        
        if new_name:
            export_data["agent"]["name"] = new_name
        else:
            # If no new name provided, append "(Clone)" to indicate it's a copy
            export_data["agent"]["name"] = export_data["agent"].get("name", "Agent") + " (Clone)"
        # §MCPTEST30 (2026-10-01): the card is imported from the SOURCE's card, so the clone's card carried the source's
        # name while the request named the clone; the card says what the agent is called
        if isinstance(export_data.get("agent_card"), dict):
            export_data["agent_card"]["name"] = export_data["agent"]["name"]
        
        # Recalculate checksum after modifications
        export_data["metadata"]["export_checksum"] = self._calculate_checksum(export_data)
        
        # Debug: Verify the DID was actually changed
        logger.info(f"Clone: Export data now has DID: {export_data['agent'].get('did', 'NOT FOUND')}")
        logger.info(f"Clone: Metadata still has original_did: {export_data['metadata'].get('original_did', 'NOT FOUND')}")
        
        # Import with skip to create clone (we already ensured unique DID)
        agent, report = await self.import_agent(
            import_data=export_data,
            developer_id=developer_id,
            db=db,
            conflict_resolution="skip",  # Skip if exists (shouldn't happen with our unique DID)
            dry_run=False
        )
        
        # Log clone event if successful
        if report["success"] and agent:
            await self._log_clone_event(
                original_did=agent_did,
                clone_did=agent.did,
                developer_id=developer_id,
                db=db
            )
        
        return agent, report
    
    async def _log_clone_event(
        self,
        original_did: str,
        clone_did: str,
        developer_id: int,
        db: AsyncSession
    ):
        """Log agent clone to event store"""
        try:
            await self.event_emitter.emit(
                event_type="AgentCloned",
                aggregate_id=clone_did,
                aggregate_type="Agent",
                data={
                    "original_did": original_did,
                    "clone_did": clone_did,
                    "developer_id": developer_id,
                    "timestamp": datetime.now(timezone.utc).isoformat()
                },
                metadata={
                    "source_service": "registry",
                    "operation": "clone"
                }
            )
        except Exception as e:
            logger.error(f"Failed to emit clone event: {e}")
            # Don't fail the clone if event emission fails


# Create singleton instance
export_import_service = ExportImportService()
