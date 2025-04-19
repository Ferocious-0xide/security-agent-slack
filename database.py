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
        """Search security knowledge using vector similarity and keyword matching."""
        try:
            logger.debug(f"Searching knowledge base for: {query}")
            
            # Count the total number of entries in the knowledge base
            db = next(self.get_db())
            total_entries = db.query(SecurityKnowledge).count()
            logger.debug(f"Total entries in knowledge base: {total_entries}")
            
            if total_entries == 0:
                logger.warning("Knowledge base is empty!")
                return []
            
            try:
                # Generate query embedding using Cohere
                logger.debug("Generating embedding for query")
                query_embedding = self.inference_client.embeddings_create(
                    model=os.getenv("EMBEDDING_MODEL_ID", "cohere-embed-multilingual"),
                    texts=[query]
                )[0]

                # Search for similar knowledge entries using SQLAlchemy
                logger.debug("Performing vector similarity search")
                results = db.query(
                    SecurityKnowledge.id,
                    SecurityKnowledge.title,
                    SecurityKnowledge.content,
                    SecurityKnowledge.category,
                    SecurityKnowledge.embedding
                ).order_by(
                    SecurityKnowledge.embedding.l2_distance(query_embedding)
                ).limit(limit).all()
                
                logger.debug(f"Vector search found {len(results)} results")
            except Exception as embed_error:
                logger.error(f"Vector search failed: {str(embed_error)}")
                logger.debug("Falling back to keyword search")
                
                # Fallback to keyword search if embedding fails
                query_terms = query.lower().split()
                results = db.query(SecurityKnowledge).filter(
                    or_(
                        *[SecurityKnowledge.title.ilike(f"%{term}%") for term in query_terms],
                        *[SecurityKnowledge.content.ilike(f"%{term}%") for term in query_terms]
                    )
                ).limit(limit).all()
                
                logger.debug(f"Keyword search found {len(results)} results")
            
            # Log details about the results
            for i, r in enumerate(results):
                logger.debug(f"Result {i+1}: '{r.title}' (id: {r.id})")
            
            # Return results as SecurityKnowledge objects
            return list(results)
            
        except Exception as e:
            logger.error(f"Error searching knowledge: {str(e)}")
            logger.error(f"Traceback: {traceback.format_exc()}")
            
            # Return empty list instead of raising exception
            logger.warning("Returning empty results due to search error")
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