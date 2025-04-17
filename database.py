from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy.exc import SQLAlchemyError
from typing import List, Optional
import logging
from models import Base, SecurityKnowledge, SecurityIncident, IncidentKnowledgeReference, SeverityLevel
from openai import OpenAI
import os
from dotenv import load_dotenv
from datetime import datetime
import traceback

logger = logging.getLogger(__name__)

class DatabaseManager:
    def __init__(self):
        load_dotenv()
        self.database_url = os.getenv('DATABASE_URL')
        if not self.database_url:
            raise ValueError("DATABASE_URL environment variable is not set")
        
        # Convert postgresql:// to postgresql+asyncpg://
        self.database_url = self.database_url.replace('postgresql://', 'postgresql+asyncpg://')
        self.engine = create_async_engine(self.database_url)
        self.SessionLocal = sessionmaker(
            self.engine,
            class_=AsyncSession,
            expire_on_commit=False
        )
        self.openai_client = OpenAI(api_key=os.getenv('OPENAI_API_KEY'))
        
    async def init_db(self):
        """Initialize the database by creating all tables."""
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
    
    async def get_db(self) -> AsyncSession:
        """Get a database session."""
        async with self.SessionLocal() as session:
            try:
                yield session
            finally:
                await session.close()
    
    async def add_security_knowledge(self, title: str, content: str, category: str) -> SecurityKnowledge:
        """Add new security knowledge with vector embedding."""
        try:
            # Generate embedding using OpenAI
            response = self.openai_client.embeddings.create(
                model="text-embedding-ada-002",
                input=content
            )
            embedding = response.data[0].embedding
            
            async with self.SessionLocal() as db:
                knowledge = SecurityKnowledge(
                    title=title,
                    content=content,
                    category=category,
                    embedding=embedding
                )
                db.add(knowledge)
                await db.commit()
                await db.refresh(knowledge)
                return knowledge
        except SQLAlchemyError as e:
            logger.error(f"Error adding security knowledge: {str(e)}")
            raise
    
    async def search_knowledge(self, query: str, limit: int = 5) -> List[SecurityKnowledge]:
        """Search security knowledge using text search."""
        try:
            async with self.SessionLocal() as db:
                # Use simple text search since we're using dummy embeddings
                results = await db.execute(
                    f"SELECT * FROM security_knowledge WHERE content ILIKE '%{query}%' LIMIT {limit}"
                )
                results = results.fetchall()
                
                if not results:
                    logger.info(f"No results found for query: {query}")
                else:
                    logger.info(f"Found {len(results)} results for query: {query}")
                
                return [SecurityKnowledge(**dict(row)) for row in results]
        except SQLAlchemyError as e:
            logger.error(f"Error searching knowledge: {str(e)}")
            logger.error(f"Traceback: {traceback.format_exc()}")
            raise
    
    async def create_incident(self, title: str, description: str, severity: SeverityLevel) -> SecurityIncident:
        """Create a new security incident."""
        try:
            async with self.SessionLocal() as db:
                incident = SecurityIncident(
                    title=title,
                    description=description,
                    severity=severity
                )
                db.add(incident)
                await db.commit()
                await db.refresh(incident)
                return incident
        except SQLAlchemyError as e:
            logger.error(f"Error creating incident: {str(e)}")
            raise
    
    async def link_knowledge_to_incident(
        self, 
        incident_id: int, 
        knowledge_id: int, 
        relevance_score: int
    ) -> IncidentKnowledgeReference:
        """Link security knowledge to an incident."""
        try:
            async with self.SessionLocal() as db:
                reference = IncidentKnowledgeReference(
                    incident_id=incident_id,
                    knowledge_id=knowledge_id,
                    relevance_score=relevance_score
                )
                db.add(reference)
                await db.commit()
                await db.refresh(reference)
                return reference
        except SQLAlchemyError as e:
            logger.error(f"Error linking knowledge to incident: {str(e)}")
            raise
    
    async def get_incident(self, incident_id: int) -> Optional[SecurityIncident]:
        """Get an incident by ID."""
        try:
            async with self.SessionLocal() as db:
                result = await db.execute(
                    f"SELECT * FROM security_incidents WHERE id = {incident_id}"
                )
                row = result.fetchone()
                if row:
                    return SecurityIncident(**dict(row))
                return None
        except SQLAlchemyError as e:
            logger.error(f"Error getting incident: {str(e)}")
            raise
    
    async def update_incident_status(self, incident_id: int, status: str) -> SecurityIncident:
        """Update an incident's status."""
        try:
            async with self.SessionLocal() as db:
                result = await db.execute(
                    f"SELECT * FROM security_incidents WHERE id = {incident_id}"
                )
                incident = result.fetchone()
                if incident:
                    incident = SecurityIncident(**dict(incident))
                    incident.status = status
                    if status == "resolved":
                        incident.resolved_at = datetime.utcnow()
                    await db.commit()
                    await db.refresh(incident)
                return incident
        except SQLAlchemyError as e:
            logger.error(f"Error updating incident status: {str(e)}")
            raise 