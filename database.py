from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.exc import SQLAlchemyError
from typing import List, Optional
import logging
from models import Base, SecurityKnowledge, SecurityIncident, IncidentKnowledgeReference, SeverityLevel, UserPrompt
from heroku_inference import InferenceClient
import os
from dotenv import load_dotenv
from datetime import datetime
import traceback
from sqlalchemy import or_
import psycopg2

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
        
        # Ensure the URL uses the postgresql dialect
        if not db_url.startswith('postgresql://'):
            db_url = db_url.replace('postgres://', 'postgresql://', 1)
        
        self.engine = create_engine(db_url)
        self.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=self.engine)
        
        # Initialize the database tables
        self.init_db()
        
    def init_db(self):
        """Initialize the database by creating all tables."""
        Base.metadata.create_all(bind=self.engine)
        
        # Ensure all required columns exist in security_knowledge table
        conn = self.engine.raw_connection()
        try:
            cursor = conn.cursor()
            
            # Check if title column exists
            cursor.execute("""
                SELECT column_name 
                FROM information_schema.columns 
                WHERE table_name='security_knowledge' 
                AND column_name='title'
            """)
            if not cursor.fetchone():
                cursor.execute("ALTER TABLE security_knowledge ADD COLUMN title VARCHAR(255) NOT NULL DEFAULT ''")
            
            # Check if category column exists
            cursor.execute("""
                SELECT column_name 
                FROM information_schema.columns 
                WHERE table_name='security_knowledge' 
                AND column_name='category'
            """)
            if not cursor.fetchone():
                cursor.execute("ALTER TABLE security_knowledge ADD COLUMN category VARCHAR(100) NOT NULL DEFAULT ''")
            
            # Check if guidance column exists
            cursor.execute("""
                SELECT column_name 
                FROM information_schema.columns 
                WHERE table_name='security_knowledge' 
                AND column_name='guidance'
            """)
            if not cursor.fetchone():
                cursor.execute("ALTER TABLE security_knowledge ADD COLUMN guidance TEXT")
            
            conn.commit()
        except Exception as e:
            conn.rollback()
            logger.error(f"Error updating security_knowledge table: {str(e)}")
            raise
        finally:
            conn.close()
    
    def get_db(self) -> Session:
        """Get a database session."""
        db = self.SessionLocal()
        try:
            yield db
        finally:
            db.close()
    
    def add_security_knowledge(self, title: str, content: str, category: str, guidance: str = None) -> Optional[SecurityKnowledge]:
        """Add new security knowledge to the database using direct SQL."""
        conn = None
        try:
            # Validate required fields
            if not title or not content or not category:
                raise ValueError("Title, content, and category are required fields")
            
            # Check if vector embeddings are supported
            has_vector = False
            embedding = None
            
            # Try to generate embedding regardless
            if self.inference_client:
                try:
                    # Generate embedding using Cohere
                    embedding_result = self.inference_client.embeddings_create(
                        model=os.getenv("EMBEDDING_MODEL_ID", "cohere-embed-multilingual"),
                        texts=[content]
                    )
                    if embedding_result and len(embedding_result) > 0:
                        embedding = embedding_result[0]
                        logger.debug("Successfully generated embedding")
                except Exception as e:
                    logger.warning(f"Error generating embedding: {str(e)}")
                    embedding = None
            
            # Use raw connection to avoid ORM issues
            conn = self.engine.raw_connection()
            cursor = conn.cursor()
            
            # Check if embedding column exists
            try:
                cursor.execute("SELECT column_name FROM information_schema.columns WHERE table_name='security_knowledge' AND column_name='embedding'")
                has_vector = cursor.fetchone() is not None
                logger.debug(f"Vector column exists: {has_vector}")
            except Exception as e:
                logger.debug(f"Error checking vector column: {e}")
                has_vector = False
            
            # Insert the knowledge article
            knowledge_id = None
            
            if has_vector and embedding:
                try:
                    # Try to use pgvector for insertion
                    vector_conn = psycopg2.connect(os.getenv("DATABASE_URL"))
                    try:
                        vector_cursor = vector_conn.cursor()
                        # Include guidance in the SQL if provided
                        if guidance:
                            vector_cursor.execute(
                                "INSERT INTO security_knowledge (title, content, category, embedding, guidance) VALUES (%s, %s, %s, %s::vector, %s) RETURNING id",
                                (title, content, category, embedding, guidance)
                            )
                        else:
                            vector_cursor.execute(
                                "INSERT INTO security_knowledge (title, content, category, embedding) VALUES (%s, %s, %s, %s::vector) RETURNING id",
                                (title, content, category, embedding)
                            )
                        knowledge_id = vector_cursor.fetchone()[0]
                        vector_conn.commit()
                        logger.debug(f"Inserted knowledge with vector embedding, id: {knowledge_id}")
                    except Exception as ve:
                        logger.warning(f"Vector insertion failed: {ve}, falling back to non-vector insertion")
                        vector_conn.rollback()
                        has_vector = False
                    finally:
                        vector_conn.close()
                except Exception as conn_err:
                    logger.warning(f"Vector connection failed: {conn_err}")
                    has_vector = False
            
            # If vector insertion failed or wasn't available, insert without embedding
            if knowledge_id is None:
                if guidance:
                    cursor.execute(
                        "INSERT INTO security_knowledge (title, content, category, guidance) VALUES (%s, %s, %s, %s) RETURNING id",
                        (title, content, category, guidance)
                    )
                else:
                    cursor.execute(
                        "INSERT INTO security_knowledge (title, content, category) VALUES (%s, %s, %s) RETURNING id",
                        (title, content, category)
                    )
                knowledge_id = cursor.fetchone()[0]
                conn.commit()
                logger.debug(f"Inserted knowledge without vector embedding, id: {knowledge_id}")
            
            # Create a SecurityKnowledge object to return
            knowledge = SecurityKnowledge(
                id=knowledge_id,
                title=title,
                content=content,
                category=category,
                guidance=guidance
            )
            
            return knowledge
            
        except Exception as e:
            if conn:
                conn.rollback()
            logger.error(f"Error adding security knowledge: {str(e)}")
            raise
        finally:
            if conn:
                conn.close()
    
    def update_embeddings(self):
        """Update embeddings for all security knowledge entries using Cohere."""
        try:
            # Get all security knowledge entries
            conn = self.engine.raw_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT id, content FROM security_knowledge")
            entries = cursor.fetchall()
            
            # Update embeddings in batches
            batch_size = 10
            for i in range(0, len(entries), batch_size):
                batch = entries[i:i + batch_size]
                texts = [entry[1] for entry in batch]
                
                try:
                    # Generate embeddings using Cohere
                    embeddings = self.inference_client.embeddings_create(
                        model=os.getenv("EMBEDDING_MODEL_ID", "cohere-embed-multilingual"),
                        texts=texts
                    )
                    
                    # Update each entry with its new embedding
                    for j, entry in enumerate(batch):
                        entry_id = entry[0]
                        embedding = embeddings[j]
                        
                        cursor.execute(
                            "UPDATE security_knowledge SET embedding = %s::vector WHERE id = %s",
                            (embedding, entry_id)
                        )
                    
                    conn.commit()
                    logger.info(f"Updated embeddings for batch {i//batch_size + 1}")
                    
                except Exception as e:
                    logger.error(f"Error generating embeddings for batch {i//batch_size + 1}: {str(e)}")
                    conn.rollback()
            
            logger.info("Finished updating all embeddings")
            
        except Exception as e:
            logger.error(f"Error updating embeddings: {str(e)}")
            if conn:
                conn.rollback()
        finally:
            if conn:
                conn.close()
    
    def search_knowledge(self, query: str, limit: int = 5) -> List[SecurityKnowledge]:
        """Search security knowledge using semantic similarity with Cohere embeddings."""
        try:
            # Generate query embedding using Cohere
            query_embedding = None
            if self.inference_client:
                try:
                    embeddings = self.inference_client.embeddings_create(
                        model=os.getenv("EMBEDDING_MODEL_ID", "cohere-embed-multilingual"),
                        texts=[query]
                    )
                    if embeddings and len(embeddings) > 0:
                        query_embedding = embeddings[0]
                except Exception as e:
                    logger.warning(f"Error generating query embedding: {str(e)}")
            
            # Use raw connection for vector operations
            conn = self.engine.raw_connection()
            cursor = conn.cursor()
            
            results = []
            if query_embedding:
                try:
                    # Try vector similarity search first
                    cursor.execute("""
                        SELECT id, title, content, category, guidance, embedding <=> %s::vector as distance
                        FROM security_knowledge
                        WHERE embedding IS NOT NULL
                        ORDER BY embedding <=> %s::vector
                        LIMIT %s
                    """, (query_embedding, query_embedding, limit))
                    
                    rows = cursor.fetchall()
                    for row in rows:
                        knowledge = SecurityKnowledge(
                            id=row[0],
                            title=row[1],
                            content=row[2],
                            category=row[3],
                            guidance=row[4]
                        )
                        if hasattr(SecurityKnowledge, 'embedding'):
                            knowledge.embedding = row[5]
                        results.append(knowledge)
                    
                    if results:
                        logger.info(f"Found {len(results)} results using vector similarity")
                        return results
                        
                except Exception as e:
                    logger.warning(f"Vector similarity search failed: {str(e)}")
            
            # Fallback to text search if vector search fails or returns no results
            cursor.execute("""
                SELECT id, title, content, category, guidance,
                       ts_rank(
                           to_tsvector('english', coalesce(title, '')) || 
                           to_tsvector('english', coalesce(content, '')) || 
                           to_tsvector('english', coalesce(category, '')),
                           plainto_tsquery('english', %s)
                       ) as rank
                FROM security_knowledge
                WHERE 
                    to_tsvector('english', coalesce(title, '')) || 
                    to_tsvector('english', coalesce(content, '')) || 
                    to_tsvector('english', coalesce(category, '')) @@ 
                    plainto_tsquery('english', %s)
                ORDER BY rank DESC
                LIMIT %s
            """, (query, query, limit))
            
            rows = cursor.fetchall()
            if not results:  # Only use text search results if vector search returned nothing
                for row in rows:
                    knowledge = SecurityKnowledge(
                        id=row[0],
                        title=row[1],
                        content=row[2],
                        category=row[3],
                        guidance=row[4]
                    )
                    results.append(knowledge)
                
                logger.info(f"Found {len(results)} results using text search")
            
            return results
            
        except Exception as e:
            logger.error(f"Error searching knowledge: {str(e)}")
            return []
        finally:
            if conn:
                conn.close()
    
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
    
    def get_knowledge_by_id(self, knowledge_id: str) -> Optional[SecurityKnowledge]:
        """Get a security knowledge article by ID."""
        try:
            db = next(self.get_db())
            return db.query(SecurityKnowledge).filter(SecurityKnowledge.id == knowledge_id).first()
        except SQLAlchemyError as e:
            logger.error(f"Error getting knowledge article: {str(e)}")
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
    
    def store_user_prompt(self, user_id: str, channel_id: str, prompt_text: str, 
                         response_text: str = None, article_id: Optional[int] = None) -> UserPrompt:
        """
        Store a user prompt and its response in the database.
        
        Args:
            user_id: The Slack user ID
            channel_id: The Slack channel ID
            prompt_text: The text of the user's prompt
            response_text: The response from Charlotte (optional)
            article_id: Reference to a security knowledge article (optional)
            
        Returns:
            UserPrompt: The created UserPrompt object
        """
        session = self.SessionLocal()
        try:
            logger.info(f"Storing user prompt from user {user_id} in channel {channel_id}")
            
            # Generate embedding if possible
            embedding = None
            if self.inference_client and hasattr(UserPrompt, 'embedding'):
                try:
                    # Generate embedding using the inference client
                    embedding_result = self.inference_client.embeddings_create(
                        model=os.getenv("EMBEDDING_MODEL_ID", "cohere-embed-multilingual"),
                        texts=[prompt_text]
                    )
                    if embedding_result and len(embedding_result) > 0:
                        embedding = embedding_result[0]
                        logger.debug("Successfully generated embedding for user prompt")
                except Exception as e:
                    logger.warning(f"Error generating embedding for user prompt: {str(e)}")
            
            # Create the UserPrompt object
            user_prompt = UserPrompt(
                user_id=user_id,
                channel_id=channel_id,
                prompt_text=prompt_text,
                response_text=response_text,
                article_id=article_id,
                created_at=datetime.utcnow()
            )
            
            # Set embedding if available
            if embedding and hasattr(user_prompt, 'embedding'):
                user_prompt.embedding = embedding
            
            # Add to session and commit
            session.add(user_prompt)
            session.commit()
            
            # Refresh to get the generated ID
            session.refresh(user_prompt)
            
            logger.info(f"Successfully stored user prompt with ID {user_prompt.id}")
            return user_prompt
            
        except Exception as e:
            session.rollback()
            logger.error(f"Error storing user prompt: {str(e)}")
            logger.error(traceback.format_exc())
            raise
        finally:
            session.close()
            
    def get_user_prompts(self, user_id: Optional[str] = None, 
                        channel_id: Optional[str] = None, 
                        limit: int = 100,
                        offset: int = 0) -> List[UserPrompt]:
        """
        Retrieve user prompts from the database with optional filtering.
        
        Args:
            user_id: Filter by Slack user ID (optional)
            channel_id: Filter by Slack channel ID (optional)
            limit: Maximum number of results to return
            offset: Offset for pagination
            
        Returns:
            List[UserPrompt]: List of UserPrompt objects
        """
        session = self.SessionLocal()
        try:
            query = session.query(UserPrompt)
            
            # Apply filters if provided
            if user_id:
                query = query.filter(UserPrompt.user_id == user_id)
            if channel_id:
                query = query.filter(UserPrompt.channel_id == channel_id)
                
            # Order by most recent first
            query = query.order_by(UserPrompt.created_at.desc())
            
            # Apply pagination
            query = query.limit(limit).offset(offset)
            
            # Execute query and return results
            results = query.all()
            return results
            
        except Exception as e:
            logger.error(f"Error retrieving user prompts: {str(e)}")
            logger.error(traceback.format_exc())
            return []
        finally:
            session.close() 