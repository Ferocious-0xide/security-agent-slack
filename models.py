from sqlalchemy import Column, Integer, String, Text, DateTime, Enum, ForeignKey, create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship
from datetime import datetime
import enum
from pgvector.sqlalchemy import Vector

Base = declarative_base()

class SeverityLevel(enum.Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"

class SecurityKnowledge(Base):
    __tablename__ = "security_knowledge"
    
    id = Column(Integer, primary_key=True)
    title = Column(String(255), nullable=False)
    content = Column(Text, nullable=False)
    category = Column(String(100), nullable=False)
    embedding = Column(Vector(1536))  # OpenAI embedding dimension
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    def __repr__(self):
        return f"<SecurityKnowledge(title='{self.title}', category='{self.category}')>"

class SecurityIncident(Base):
    __tablename__ = "security_incidents"
    
    id = Column(Integer, primary_key=True)
    title = Column(String(255), nullable=False)
    description = Column(Text, nullable=False)
    severity = Column(Enum(SeverityLevel), nullable=False)
    status = Column(String(50), default="open")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    resolved_at = Column(DateTime, nullable=True)
    
    # Relationships
    knowledge_references = relationship("IncidentKnowledgeReference", back_populates="incident")
    
    def __repr__(self):
        return f"<SecurityIncident(title='{self.title}', severity='{self.severity}')>"

class IncidentKnowledgeReference(Base):
    __tablename__ = "incident_knowledge_references"
    
    id = Column(Integer, primary_key=True)
    incident_id = Column(Integer, ForeignKey("security_incidents.id"), nullable=False)
    knowledge_id = Column(Integer, ForeignKey("security_knowledge.id"), nullable=False)
    relevance_score = Column(Integer, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Relationships
    incident = relationship("SecurityIncident", back_populates="knowledge_references")
    knowledge = relationship("SecurityKnowledge")
    
    def __repr__(self):
        return f"<IncidentKnowledgeReference(incident_id={self.incident_id}, knowledge_id={self.knowledge_id})>" 