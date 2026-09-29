-- MineIntel AI - PostgreSQL initialization
-- Enables pgvector for RAG embeddings

CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Placeholder comment: tables are created by SQLAlchemy on startup.
-- Vector columns (document_chunks.embedding) use Vector(EMBEDDING_DIMENSIONS).
