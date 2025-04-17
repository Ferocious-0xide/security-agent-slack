from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy import text
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
            logger.info(f"Starting database search for query: {query}")
            async with self.SessionLocal() as db:
                logger.info("Database session established")
                
                # Split query into words and create a more flexible search pattern
                words = query.split()
                search_patterns = [f"%{word}%" for word in words]
                logger.info(f"Search patterns: {search_patterns}")
                
                # Use SQLAlchemy's text() function for raw SQL
                sql = text("""
                    SELECT id, title, content, category, embedding, created_at, updated_at 
                    FROM security_knowledge 
                    WHERE content ILIKE ANY(:patterns)
                    ORDER BY created_at DESC
                    LIMIT :limit
                """)
                
                logger.info("Executing SQL query")
                results = await db.execute(
                    sql,
                    {"patterns": search_patterns, "limit": limit}
                )
                results = results.fetchall()
                logger.info(f"Query executed, found {len(results)} rows")
                
                if not results:
                    logger.info(f"No results found for query: {query}")
                    return []
                
                # Convert results to SecurityKnowledge objects
                knowledge_results = []
                for row in results:
                    try:
                        logger.info(f"Processing row: {row}")
                        knowledge = SecurityKnowledge(
                            id=row[0],
                            title=row[1],
                            content=row[2],
                            category=row[3],
                            embedding=row[4],
                            created_at=row[5],
                            updated_at=row[6]
                        )
                        logger.info(f"Created SecurityKnowledge object: {knowledge}")
                        knowledge_results.append(knowledge)
                    except Exception as e:
                        logger.error(f"Error converting row to SecurityKnowledge: {str(e)}")
                        logger.error(f"Row data: {row}")
                        logger.error(f"Traceback: {traceback.format_exc()}")
                        continue
                
                logger.info(f"Successfully converted {len(knowledge_results)} results")
                return knowledge_results
                
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
                sql = text("""
                    SELECT * FROM security_incidents 
                    WHERE id = :incident_id
                """)
                
                result = await db.execute(
                    sql,
                    {"incident_id": incident_id}
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
                sql = text("""
                    SELECT * FROM security_incidents 
                    WHERE id = :incident_id
                """)
                
                result = await db.execute(
                    sql,
                    {"incident_id": incident_id}
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