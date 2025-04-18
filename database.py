from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.exc import SQLAlchemyError
from typing import List, Optional
import logging
from models import Base, SecurityKnowledge, SecurityIncident, IncidentKnowledgeReference, SeverityLevel
from heroku_inference import InferenceClient
import os
from dotenv import load_dotenv
from datetime import datetime
import traceback
from sqlalchemy import or_

logger = logging.getLogger(__name__)

class DatabaseManager:
    def __init__(self):
        """Initialize the database manager."""
        load_dotenv()
        
        # Initialize Heroku Inference client
        self.inference_client = InferenceClient()
        
        # Get database URL from environment
        db_url = os.getenv('DATABASE_URL')
        if not db_url:
            raise ValueError("DATABASE_URL environment variable not set")
        
        self.engine = create_engine(db_url)
        self.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=self.engine)
        
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
    
    def add_security_knowledge(self, title: str, content: str, category: str) -> Optional[SecurityKnowledge]:
        """Add new security knowledge to the database."""
        try:
            # Generate embedding using Cohere
            embedding = self.inference_client.embeddings_create(
                model="cohere/embed-english-v3.0",
                texts=[content]
            )[0]
            
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
    
    def search_knowledge(self, query: str, limit: int = 5) -> List[SecurityKnowledge]:
        """Search security knowledge using vector similarity."""
        try:
            # Generate query embedding using Cohere
            query_embedding = self.inference_client.embeddings_create(
                model="cohere/embed-english-v3.0",
                texts=[query]
            )[0]

            # Search for similar knowledge entries
            db = next(self.get_db())
            cursor = db.cursor()
            cursor.execute("""
                SELECT id, title, content, category, embedding,
                       (embedding <=> %s) as distance
                FROM security_knowledge
                ORDER BY distance ASC
                LIMIT %s
            """, (query_embedding, limit))
            
            results = []
            for row in cursor.fetchall():
                knowledge = SecurityKnowledge(
                    id=row[0],
                    title=row[1],
                    content=row[2],
                    category=row[3],
                    embedding=row[4]
                )
                results.append(knowledge)
            
            return results

        except Exception as e:
            logging.error(f"Error searching knowledge: {str(e)}")
            return []
    
    def create_incident(self, title: str, description: str, severity: SeverityLevel) -> SecurityIncident:
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
    
    def link_knowledge_to_incident(
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
    
    def get_incident(self, incident_id: int) -> Optional[SecurityIncident]:
        """Get an incident by ID."""
        try:
            db = next(self.get_db())
            return db.query(SecurityIncident).filter(SecurityIncident.id == incident_id).first()
        except SQLAlchemyError as e:
            logger.error(f"Error getting incident: {str(e)}")
            raise
    
    def update_incident_status(self, incident_id: int, status: str) -> SecurityIncident:
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