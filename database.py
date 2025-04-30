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
    
    def search_knowledge(self, query: str, limit: int = 10) -> List[SecurityKnowledge]:
        """Search security knowledge using keyword matching (fallback from vector search)."""
        try:
            print(f"\n[SEARCH] Searching knowledge base for: '{query}'")
            logger.info(f"========== SEARCH QUERY: '{query}' ==========")
            
            # Break query into terms for keyword search
            query_terms = [term.strip() for term in query.lower().split() if term.strip()]
            if not query_terms:
                query_terms = [""]  # Use empty term if no valid terms
                
            print(f"[SEARCH] Search terms: {', '.join(query_terms) if query_terms[0] else 'empty query'}")
            logger.info(f"Search terms: {query_terms}")
                
            # Use raw SQL to avoid ORM issues with missing columns
            conn = self.engine.raw_connection()
            try:
                cursor = conn.cursor()
                
                # Check total entries
                cursor.execute("SELECT COUNT(*) FROM security_knowledge")
                total_entries = cursor.fetchone()[0]
                print(f"[SEARCH] Total articles in knowledge base: {total_entries}")
                logger.info(f"Total entries in knowledge base: {total_entries}")
                
                if total_entries == 0:
                    logger.warning("Knowledge base is empty!")
                    print("[SEARCH ERROR] Knowledge base is empty!")
                    return []
                
                # Check if vector column exists
                has_vector = False
                try:
                    cursor.execute("SELECT column_name FROM information_schema.columns WHERE table_name='security_knowledge' AND column_name='embedding'")
                    has_vector = cursor.fetchone() is not None
                    logger.info(f"Vector column exists: {has_vector}")
                except Exception as e:
                    logger.debug(f"Error checking vector column: {e}")
                    has_vector = False
                
                print(f"[SEARCH] Vector search available: {has_vector}")
                
                results = []
                
                # Always do keyword search first
                if query_terms:
                    # Build SQL for keyword search
                    sql_conditions = []
                    sql_params = []
                    
                    for i, term in enumerate(query_terms):
                        if term:
                            sql_conditions.append(f"(title ILIKE %s OR content ILIKE %s OR category ILIKE %s)")
                            sql_params.extend([f"%{term}%", f"%{term}%", f"%{term}%"])
                    
                    if sql_conditions:
                        # First check if guidance column exists
                        try:
                            cursor.execute("SELECT column_name FROM information_schema.columns WHERE table_name='security_knowledge' AND column_name='guidance'")
                            guidance_exists = cursor.fetchone() is not None
                        except Exception as e:
                            logger.debug(f"Error checking guidance column: {e}")
                            guidance_exists = False
                            
                        # Construct SQL based on whether guidance column exists
                        if guidance_exists:
                            sql = f"""
                                SELECT id, title, content, category, guidance 
                                FROM security_knowledge 
                                WHERE {' OR '.join(sql_conditions)}
                                ORDER BY 
                                    CASE 
                                        WHEN title ILIKE %s THEN 1
                                        WHEN category ILIKE %s THEN 2
                                        ELSE 3
                                    END,
                                    id DESC
                                LIMIT %s
                            """
                            sql_params.extend([f"%{query_terms[0]}%", f"%{query_terms[0]}%"])
                        else:
                            sql = f"""
                                SELECT id, title, content, category 
                                FROM security_knowledge 
                                WHERE {' OR '.join(sql_conditions)}
                                ORDER BY 
                                    CASE 
                                        WHEN title ILIKE %s THEN 1
                                        WHEN category ILIKE %s THEN 2
                                        ELSE 3
                                    END,
                                    id DESC
                                LIMIT %s
                            """
                            sql_params.extend([f"%{query_terms[0]}%", f"%{query_terms[0]}%"])
                        
                        # Ensure limit is always applied
                        sql_params.append(min(limit, 20))  # Increased from 5 to 20
                        
                        print(f"[SEARCH] Executing keyword search with limit {min(limit, 20)}...")
                        cursor.execute(sql, sql_params)
                        keyword_rows = cursor.fetchall()
                        print(f"[SEARCH] Keyword search found {len(keyword_rows)} results")
                        logger.info(f"Keyword search found {len(keyword_rows)} results")
                        
                        # Convert to SecurityKnowledge objects
                        for row in keyword_rows:
                            knowledge = SecurityKnowledge(
                                id=row[0],
                                title=row[1],
                                content=row[2],
                                category=row[3],
                                guidance=row[4] if len(row) > 4 else None
                            )
                            results.append(knowledge)
                            print(f"[SEARCH RESULT] #{knowledge.id}: {knowledge.title} (Category: {knowledge.category})")
                
                # Try vector search if available
                if has_vector and self.inference_client and query:
                    try:
                        # Generate embedding
                        print(f"[SEARCH] Attempting vector search...")
                        embeddings = self.inference_client.embeddings_create(
                            model=os.getenv("EMBEDDING_MODEL_ID", "cohere-embed-multilingual"),
                            texts=[query]
                        )
                        
                        if embeddings and len(embeddings) > 0:
                            # Need a different connection with pgvector extension
                            vector_conn = psycopg2.connect(os.getenv("DATABASE_URL"))
                            try:
                                vector_cursor = vector_conn.cursor()
                                
                                # Try different distance methods (these work even if pgvector isn't fully available)
                                for distance_method in ["<->", "cosine_distance", "l2_distance"]:
                                    try:
                                        # First check if guidance column exists
                                        try:
                                            vector_cursor.execute("SELECT column_name FROM information_schema.columns WHERE table_name='security_knowledge' AND column_name='guidance'")
                                            guidance_exists = vector_cursor.fetchone() is not None
                                        except Exception as e:
                                            logger.debug(f"Error checking guidance column: {e}")
                                            guidance_exists = False
                                            
                                        # Construct SQL based on whether guidance column exists
                                        if guidance_exists:
                                            sql = f"""
                                                SELECT id, title, content, category, guidance
                                                FROM security_knowledge
                                                ORDER BY embedding {distance_method} %s::vector
                                                LIMIT %s
                                            """
                                        else:
                                            sql = f"""
                                                SELECT id, title, content, category
                                                FROM security_knowledge
                                                ORDER BY embedding {distance_method} %s::vector
                                                LIMIT %s
                                            """
                                        
                                        vector_cursor.execute(sql, (embeddings[0], min(limit, 20)))
                                        vector_rows = vector_cursor.fetchall()
                                        
                                        if vector_rows:
                                            print(f"[SEARCH] Vector search ({distance_method}) found {len(vector_rows)} results")
                                            logger.info(f"Vector search ({distance_method}) found {len(vector_rows)} results")
                                            
                                            # Create vector results
                                            vector_results = []
                                            for row in vector_rows:
                                                knowledge = SecurityKnowledge(
                                                    id=row[0],
                                                    title=row[1],
                                                    content=row[2],
                                                    category=row[3],
                                                    guidance=row[4] if len(row) > 4 else None
                                                )
                                                vector_results.append(knowledge)
                                                print(f"[VECTOR RESULT] #{knowledge.id}: {knowledge.title}")
                                            
                                            # Merge with keyword results
                                            existing_ids = {k.id for k in results}
                                            added_count = 0
                                            for vr in vector_results:
                                                if vr.id not in existing_ids:
                                                    results.append(vr)
                                                    added_count += 1
                                                    if len(results) >= limit:
                                                        break
                                                        
                                            print(f"[SEARCH] Added {added_count} unique vector results to final results")
                                            # Found results with this method, no need to try others
                                            break
                                    except Exception as vector_error:
                                        logger.debug(f"Vector search method {distance_method} failed: {vector_error}")
                                        continue
                            finally:
                                vector_conn.close()
                    except Exception as e:
                        logger.error(f"Vector search failed: {str(e)}")
                        print(f"[SEARCH ERROR] Vector search failed: {str(e)}")
                
                # Log details about the final results
                print(f"\n[SEARCH] === FINAL RESULTS ({len(results[:min(limit, 20)])}) ===")
                for i, r in enumerate(results[:min(limit, 20)]):
                    print(f"[SEARCH RESULT {i+1}] {r.title} (Category: {r.category})")
                    # Print a snippet of the content
                    content_snippet = r.content[:100] + "..." if len(r.content) > 100 else r.content
                    print(f"  Content snippet: {content_snippet}")
                    logger.info(f"Result {i+1}: '{r.title}' (id: {r.id})")
                
                if not results:
                    print("[SEARCH] No results found for your query.")
                
                print("\n")
                # Strictly enforce result limit to maximum of 20
                return results[:min(limit, 20)]
            finally:
                conn.close()
        except Exception as e:
            error_msg = f"Error searching knowledge: {str(e)}"
            logger.error(error_msg)
            logger.error(f"Traceback: {traceback.format_exc()}")
            print(f"[SEARCH ERROR] {error_msg}")
            
            # In case of error, try a final fallback with minimalistic direct query 
            try:
                print("[SEARCH] Attempting fallback query...")
                conn = self.engine.raw_connection()
                cursor = conn.cursor()
                
                # Check if guidance column exists first
                try:
                    cursor.execute("SELECT column_name FROM information_schema.columns WHERE table_name='security_knowledge' AND column_name='guidance'")
                    guidance_exists = cursor.fetchone() is not None
                except Exception as e:
                    logger.debug(f"Error checking guidance column: {e}")
                    guidance_exists = False
                
                # Use a hard limit of 20 results
                if guidance_exists:
                    cursor.execute("SELECT id, title, content, category, guidance FROM security_knowledge LIMIT %s", (min(limit, 20),))
                else:
                    cursor.execute("SELECT id, title, content, category FROM security_knowledge LIMIT %s", (min(limit, 20),))
                
                rows = cursor.fetchall()
                
                fallback_results = []
                for row in rows:
                    knowledge = SecurityKnowledge(
                        id=row[0],
                        title=row[1],
                        content=row[2],
                        category=row[3],
                        guidance=row[4] if len(row) > 4 else None
                    )
                    fallback_results.append(knowledge)
                    print(f"[FALLBACK RESULT] #{knowledge.id}: {knowledge.title}")
                
                print(f"[SEARCH] Using fallback query, found {len(fallback_results)} results")
                logger.warning(f"Using fallback query, found {len(fallback_results)} results")
                return fallback_results
            except Exception as fallback_error:
                logger.error(f"Even fallback query failed: {fallback_error}")
                print(f"[SEARCH ERROR] Even fallback query failed: {fallback_error}")
                
            # Return empty list as last resort
            logger.warning("Returning empty results due to search error")
            print("[SEARCH] Returning empty results due to search error")
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