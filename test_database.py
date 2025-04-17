import pytest
import os
from database import DatabaseManager
from models import SeverityLevel
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from unittest.mock import patch, MagicMock

@pytest.fixture
def db_manager():
    with patch.dict(os.environ, {
        'DATABASE_URL': 'postgresql://test:test@localhost/test_db',
        'OPENAI_API_KEY': 'test_key'
    }):
        manager = DatabaseManager()
        # Create test tables
        manager.init_db()
        yield manager
        # Clean up test tables
        Base.metadata.drop_all(bind=manager.engine)

@pytest.mark.asyncio
async def test_add_security_knowledge(db_manager):
    with patch('openai.OpenAI.embeddings.create') as mock_embedding:
        mock_embedding.return_value = MagicMock(
            data=[MagicMock(embedding=[0.1] * 1536)]
        )
        
        knowledge = await db_manager.add_security_knowledge(
            title="Test Security Issue",
            content="This is a test security issue",
            category="vulnerability"
        )
        
        assert knowledge.title == "Test Security Issue"
        assert knowledge.content == "This is a test security issue"
        assert knowledge.category == "vulnerability"
        assert len(knowledge.embedding) == 1536

@pytest.mark.asyncio
async def test_search_knowledge(db_manager):
    with patch('openai.OpenAI.embeddings.create') as mock_embedding:
        mock_embedding.return_value = MagicMock(
            data=[MagicMock(embedding=[0.1] * 1536)]
        )
        
        # First add some test knowledge
        await db_manager.add_security_knowledge(
            title="Test Security Issue",
            content="This is a test security issue",
            category="vulnerability"
        )
        
        # Then search for it
        results = await db_manager.search_knowledge("test security")
        assert len(results) > 0
        assert results[0].title == "Test Security Issue"

@pytest.mark.asyncio
async def test_create_incident(db_manager):
    incident = await db_manager.create_incident(
        title="Test Incident",
        description="This is a test incident",
        severity=SeverityLevel.HIGH
    )
    
    assert incident.title == "Test Incident"
    assert incident.description == "This is a test incident"
    assert incident.severity == SeverityLevel.HIGH
    assert incident.status == "open"

@pytest.mark.asyncio
async def test_link_knowledge_to_incident(db_manager):
    with patch('openai.OpenAI.embeddings.create') as mock_embedding:
        mock_embedding.return_value = MagicMock(
            data=[MagicMock(embedding=[0.1] * 1536)]
        )
        
        # Create test knowledge and incident
        knowledge = await db_manager.add_security_knowledge(
            title="Test Knowledge",
            content="Test content",
            category="test"
        )
        
        incident = await db_manager.create_incident(
            title="Test Incident",
            description="Test description",
            severity=SeverityLevel.MEDIUM
        )
        
        # Link them
        reference = await db_manager.link_knowledge_to_incident(
            incident_id=incident.id,
            knowledge_id=knowledge.id,
            relevance_score=90
        )
        
        assert reference.incident_id == incident.id
        assert reference.knowledge_id == knowledge.id
        assert reference.relevance_score == 90

@pytest.mark.asyncio
async def test_update_incident_status(db_manager):
    # Create test incident
    incident = await db_manager.create_incident(
        title="Test Incident",
        description="Test description",
        severity=SeverityLevel.LOW
    )
    
    # Update status
    updated_incident = await db_manager.update_incident_status(
        incident_id=incident.id,
        status="in_progress"
    )
    
    assert updated_incident.status == "in_progress"
    
    # Test resolution
    resolved_incident = await db_manager.update_incident_status(
        incident_id=incident.id,
        status="resolved"
    )
    
    assert resolved_incident.status == "resolved"
    assert resolved_incident.resolved_at is not None 