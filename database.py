from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.exc import SQLAlchemyError
from typing import List, Optional
import logging
from models import Base, SecurityKnowledge, SecurityIncident, IncidentKnowledgeReference, SeverityLevel
from openai import OpenAI
import os
from dotenv import load_dotenv
from datetime import datetime

logger = logging.getLogger(__name__)

class DatabaseManager:
    def __init__(self):
        load_dotenv()
        self.database_url = os.getenv('DATABASE_URL')
        if not self.database_url:
            raise ValueError("DATABASE_URL environment variable is not set")
        
        self.engine = create_engine(self.database_url)
        self.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=self.engine)
        self.openai_client = OpenAI(api_key=os.getenv('OPENAI_API_KEY'))
        
    def init_db(self):
        """Initialize the database by creating all tables."""
        Base.metadata.create_all(bind=self.engine)
    
    def get_db(self) -> Session:
        """Get a database session."""
        db = self.SessionLocal()
        try:
            yield db
        finally:
            db.close()
    
    async def add_security_knowledge(self, title: str, content: str, category: str) -> SecurityKnowledge:
        """Add new security knowledge with vector embedding."""
        try:
            # Generate embedding using OpenAI
            response = self.openai_client.embeddings.create(
                model="text-embedding-ada-002",
                input=content
            )
            embedding = response.data[0].embedding
            
            db = next(self.get_db())
            knowledge = SecurityKnowledge(
                title=title,
                content=content,
                category=category,
                embedding=embedding
            )
            db.add(knowledge)
            db.commit()
            db.refresh(knowledge)
            return knowledge
        except SQLAlchemyError as e:
            logger.error(f"Error adding security knowledge: {str(e)}")
            raise
    
    async def search_knowledge(self, query: str, limit: int = 5) -> List[SecurityKnowledge]:
        """Search security knowledge using vector similarity."""
        try:
            # Generate query embedding
            response = self.openai_client.embeddings.create(
                model="text-embedding-ada-002",
                input=query
            )
            query_embedding = response.data[0].embedding
            
            db = next(self.get_db())
            results = db.query(SecurityKnowledge).order_by(
                SecurityKnowledge.embedding.cosine_distance(query_embedding)
            ).limit(limit).all()
            
            return results
        except SQLAlchemyError as e:
            logger.error(f"Error searching knowledge: {str(e)}")
            raise
    
    async def create_incident(self, title: str, description: str, severity: SeverityLevel) -> SecurityIncident:
        """Create a new security incident."""
        try:
            db = next(self.get_db())
            incident = SecurityIncident(
                title=title,
                description=description,
                severity=severity
            )
            db.add(incident)
            db.commit()
            db.refresh(incident)
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
            db = next(self.get_db())
            reference = IncidentKnowledgeReference(
                incident_id=incident_id,
                knowledge_id=knowledge_id,
                relevance_score=relevance_score
            )
            db.add(reference)
            db.commit()
            db.refresh(reference)
            return reference
        except SQLAlchemyError as e:
            logger.error(f"Error linking knowledge to incident: {str(e)}")
            raise
    
    async def get_incident(self, incident_id: int) -> Optional[SecurityIncident]:
        """Get an incident by ID."""
        try:
            db = next(self.get_db())
            return db.query(SecurityIncident).filter(SecurityIncident.id == incident_id).first()
        except SQLAlchemyError as e:
            logger.error(f"Error getting incident: {str(e)}")
            raise
    
    async def update_incident_status(self, incident_id: int, status: str) -> SecurityIncident:
        """Update an incident's status."""
        try:
            db = next(self.get_db())
            incident = db.query(SecurityIncident).filter(SecurityIncident.id == incident_id).first()
            if incident:
                incident.status = status
                if status == "resolved":
                    incident.resolved_at = datetime.utcnow()
                db.commit()
                db.refresh(incident)
            return incident
        except SQLAlchemyError as e:
            logger.error(f"Error updating incident status: {str(e)}")
            raise 